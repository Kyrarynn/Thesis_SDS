"""
Corrects the IQ-rating / audio-file shift in sessions recorded before the
index.html fix of 2026-10-08.

Bug: when Rasa returned an EMPTY bot reply, the frontend showed no rating and
did not advance turnIndex, but FastAPI still stored the turn. So:
  - rating number k was written to turns[k], but belongs to the k-th turn
    WITH a bot reply;
  - the audio file "..._turnN.webm" was overwritten by every recording made
    while turnIndex == N; the surviving file belongs to the LAST of those
    user turns. Audio of the other turns is lost.

The script does NOT change iq_rating. It adds per turn:
  iq_rating_corrected   rating that belongs to this turn (None if not rated)
  audio_turn_file       N of the "..._turnN.webm" file holding this turn's
                        audio, or None if that recording was overwritten

Usage (PowerShell, in venv_api):
  python fix_ratings.py            # dry run: prints the mapping
  python fix_ratings.py --apply    # writes the two fields to MongoDB
"""
import sys
from pymongo import MongoClient


def correct(turns):
    rated = [i for i, t in enumerate(turns) if t.get("bot_text")]
    stored = [t.get("iq_rating") for t in turns]

    corrected = [None] * len(turns)
    for k, i in enumerate(rated):
        corrected[i] = stored[k] if k < len(stored) else None

    # turnIndex the frontend had when turn i was recorded
    idx, n = [], 0
    for t in turns:
        idx.append(n)
        if t.get("bot_text"):
            n += 1
    audio = [idx[i] if (i + 1 == len(turns) or idx[i + 1] != idx[i]) else None
             for i in range(len(turns))]
    return corrected, audio


def main(apply):
    db = MongoClient("mongodb://localhost:27017")["sds_study"]
    for doc in db.sessions.find().sort("start_time", 1):
        turns = doc.get("turns") or []
        if not turns:
            continue
        corrected, audio = correct(turns)
        n_empty = sum(1 for t in turns if not t.get("bot_text"))
        print(f"\n{doc.get('participant_code')} {doc.get('system_version')} "
              f"{doc['participant_id'][:8]}  turns={len(turns)} empty_bot_replies={n_empty}")
        if n_empty == 0:
            print("  no shift (no empty bot replies)")
        for i, t in enumerate(turns):
            if n_empty:
                print(f"  {i:2} stored={t.get('iq_rating')!s:4} corrected={corrected[i]!s:4} "
                      f"audio=turn{audio[i]!s:4} | {t.get('user_text','')[:35]!r:38} -> {t.get('bot_text','')[:35]!r}")
        if apply:
            db.sessions.update_one({"_id": doc["_id"]}, {"$set": {
                **{f"turns.{i}.iq_rating_corrected": corrected[i] for i in range(len(turns))},
                **{f"turns.{i}.audio_turn_file": audio[i] for i in range(len(turns))},
            }})
    print("\nWritten." if apply else "\nDry run - nothing written. Use --apply to write.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
