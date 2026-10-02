"""
Quality check for the recorded .webm files before/while running the study.

For every recording it
  1. converts .webm -> 16 kHz mono .wav with ffmpeg (OpenSMILE cannot read webm),
  2. measures duration, loudness, clipping and the share of near-silence,
  3. extracts the eGeMAPS feature set with OpenSMILE and checks it is complete,
and writes everything to audio_check_report.csv plus a short summary.

Requirements (once, in the environment you use for analysis):
    pip install opensmile pandas numpy soundfile
ffmpeg must be on PATH (it already is, Whisper needs it too).

Usage (PowerShell, inside your project folder):
    python check_audio.py                       # checks audio_recordings/
    python check_audio.py path\to\folder        # checks another folder
"""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import opensmile
import pandas as pd
import soundfile as sf

AUDIO_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("audio_recordings")
WAV_DIR = AUDIO_DIR / "wav_16k"
REPORT = Path("audio_check_report.csv")

# Thresholds for warnings (adjust after looking at your pilot data)
MIN_DURATION_S = 0.5      # shorter = probably button released too early
MAX_DURATION_S = 30.0     # longer = button probably held by accident
MIN_RMS_DBFS = -45.0      # quieter = mic too far away / wrong input device
MAX_CLIP_SHARE = 0.001    # >0.1 % of samples at full scale = clipping
MAX_SILENCE_SHARE = 0.80  # >80 % near-silence = little actual speech

if shutil.which("ffmpeg") is None:
    sys.exit("ffmpeg not found on PATH")

smile = opensmile.Smile(
    feature_set=opensmile.FeatureSet.eGeMAPSv02,
    feature_level=opensmile.FeatureLevel.Functionals,
)


def to_wav(src: Path) -> Path:
    dst = WAV_DIR / (src.stem + ".wav")
    if not dst.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(dst)],
            check=True, capture_output=True,
        )
    return dst


def check(path: Path) -> dict:
    row = {"file": path.name, "ok": True, "problems": ""}
    problems = []
    try:
        wav = to_wav(path)
    except subprocess.CalledProcessError:
        return {**row, "ok": False, "problems": "cannot decode (corrupt/empty file)"}

    x, sr = sf.read(wav, dtype="float32")
    dur = len(x) / sr
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    rms_db = 20 * np.log10(rms) if rms > 0 else -120.0
    clip = float(np.mean(np.abs(x) >= 0.999)) if len(x) else 0.0

    # near-silence: 25 ms frames more than 35 dB below the loudest frame
    frame = int(0.025 * sr)
    n = len(x) // frame
    if n:
        fr = x[: n * frame].reshape(n, frame)
        fdb = 20 * np.log10(np.sqrt(np.mean(fr ** 2, axis=1)) + 1e-10)
        silence = float(np.mean(fdb < fdb.max() - 35))
    else:
        silence = 1.0

    row.update(duration_s=round(dur, 2), rms_dbfs=round(rms_db, 1),
               clipped_share=round(clip, 5), silence_share=round(silence, 2))

    if dur < MIN_DURATION_S: problems.append("too short")
    if dur > MAX_DURATION_S: problems.append("too long")
    if rms_db < MIN_RMS_DBFS: problems.append("too quiet")
    if clip > MAX_CLIP_SHARE: problems.append("clipping")
    if silence > MAX_SILENCE_SHARE: problems.append("mostly silence")

    # OpenSMILE: does feature extraction work and give complete values?
    try:
        feats = smile.process_file(str(wav))
        nan = int(feats.isna().sum().sum())
        row["egemaps_features"] = feats.shape[1]
        row["egemaps_nan"] = nan
        row["mean_F0_semitone"] = round(float(feats["F0semitoneFrom27.5Hz_sma3nz_amean"].iloc[0]), 2)
        row["voiced_segments_per_s"] = round(float(feats["VoicedSegmentsPerSec"].iloc[0]), 2)
        if nan: problems.append(f"{nan} NaN features")
        if row["voiced_segments_per_s"] == 0: problems.append("no voiced speech detected")
    except Exception as e:  # noqa: BLE001
        problems.append(f"OpenSMILE failed: {e}")

    row["ok"] = not problems
    row["problems"] = "; ".join(problems)
    return row


def main():
    files = sorted(AUDIO_DIR.glob("*.webm"))
    if not files:
        sys.exit(f"No .webm files in {AUDIO_DIR.resolve()}")
    WAV_DIR.mkdir(exist_ok=True)

    rows = []
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f.name}", end="\r")
        rows.append(check(f))
    df = pd.DataFrame(rows)
    df.to_csv(REPORT, index=False)

    print(f"\nChecked {len(df)} files -> {REPORT}")
    print(f"OK: {df['ok'].sum()}   with problems: {(~df['ok']).sum()}")
    if "duration_s" in df:
        print(f"Duration  median {df['duration_s'].median():.1f} s  "
              f"(min {df['duration_s'].min():.1f}, max {df['duration_s'].max():.1f})")
        print(f"Loudness  median {df['rms_dbfs'].median():.1f} dBFS")
    bad = df[~df["ok"]]
    if len(bad):
        print("\nFiles with problems:")
        print(bad[["file", "problems"]].to_string(index=False))


if __name__ == "__main__":
    main()