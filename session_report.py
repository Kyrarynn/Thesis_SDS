"""
Session overview for the thesis documentation (manipulation check).

Reads all conversation sessions from MongoDB and writes one row per session
to session_report.csv (semicolon-separated, opens directly in German Excel).

Columns
  participant_code, condition      P05, A / B
  start_local                      start time (Europe/Berlin)
  version                          v1 = before the fix of 08.10.2026, v2 = after
  n_turns                          logged user turns
  error_fired                      yes / no  (planned error actually shown?)
  error_turn                       turn index where it was shown
  cause_if_not                     probable reason if the error did not fire
  empty_bot_replies                turns without any bot reply
  ratings_shifted                  yes = run fix_ratings.py for this session
  lost_audio_turns                 audio files overwritten (v1 only)
  booking_confirmed                yes / no
  n_ratings                        stored IQ ratings

Usage (PowerShell, in venv_api, MongoDB running):
  python session_report.py
  python session_report.py --fix-time 2026-10-08T21:30:00Z   # other cut-off
"""
import csv
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Moment the fixed actions.py / index.html were in place (UTC).
# Sessions started before are "v1". Adjust with --fix-time if needed.
DEFAULT_FIX_TIME = "2026-10-08T21:30:00Z"

A_ERROR = 'did you say "'                       # System A: misheard preference
B_ERROR = "having trouble processing the date"  # System B: date failure
FOOD_QUESTION = "dietary preferences"
FORM_FALLBACK = ("didn't understand that preference", "didn't catch that")
RECOMMENDATIONS = "restaurants in"
SUMMARY = "To confirm:"
CONFIRMED = "reservation is confirmed"


def to_dt(v):
    """datetime from pymongo or {"$date": "..."} from a JSON export."""
    if isinstance(v, dict) and "$date" in v:
        v = v["$date"]
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if v is not None and v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)   # pymongo returns naive UTC
    return v


def first_index(turns, text):
    return next((i for i, t in enumerate(turns) if text in (t.get("bot_text") or "")), None)


def analyse(doc, fix_time):
    turns = doc.get("turns") or []
    cond = doc.get("system_version")
    bots = [t.get("bot_text") or "" for t in turns]
    start = to_dt(doc.get("start_time"))
    version = "v1" if start and start < fix_time else "v2"

    empty = sum(1 for b in bots if not b)
    error_turn = first_index(turns, A_ERROR if cond == "A" else B_ERROR)
    fired = error_turn is not None

    cause = ""
    if not fired:
        q = first_index(turns, FOOD_QUESTION)
        rec = first_index(turns, RECOMMENDATIONS)
        summ = first_index(turns, SUMMARY)
        if not turns:
            cause = "no turns logged"
        elif version == "v1" and not bots[0]:
            cause = "fallback on first utterance -> condition lost (bug 1)"
        elif cond == "A" and q is None:
            cause = "dietary question never reached"
        elif cond == "A" and rec is not None and rec > 0 and any(
                f in bots[rec - 1] for f in FORM_FALLBACK):
            cause = "answer right after form fallback -> validation skipped (bug 2)"
        elif cond == "A" and rec is None:
            cause = "recommendations never reached"
        elif cond == "B" and summ is None:
            cause = "booking summary never reached"
        else:
            cause = "unclear - check log manually"

    # audio files overwritten in v1: user turns followed by an empty reply
    # (except the very last turn, whose file was not overwritten)
    lost_audio = [i for i, b in enumerate(bots[:-1]) if not b] if version == "v1" else []

    return {
        "participant_code": doc.get("participant_code"),
        "condition": cond,
        "session_id": (doc.get("participant_id") or "")[:8],
        "start_local": start.astimezone(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M") if start else "",
        "version": version,
        "n_turns": len(turns),
        "error_fired": "yes" if fired else "no",
        "error_turn": "" if error_turn is None else error_turn,
        "cause_if_not": cause,
        "empty_bot_replies": empty,
        "ratings_shifted": "yes" if version == "v1" and empty else "no",
        "lost_audio_turns": ",".join(map(str, lost_audio)),
        "booking_confirmed": "yes" if first_index(turns, CONFIRMED) is not None else "no",
        "n_ratings": sum(1 for t in turns if t.get("iq_rating") is not None),
    }


def write_report(rows, path="session_report.csv"):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
        w.writeheader()
        w.writerows(rows)

    print(f"{len(rows)} sessions -> {path}\n")
    print(f"{'Code':5} {'Cond':4} {'Ver':3} {'Fired':5} {'Empty':5}  Cause")
    for r in rows:
        print(f"{r['participant_code'] or '?':5} {r['condition'] or '?':4} {r['version']:3} "
              f"{r['error_fired']:5} {r['empty_bot_replies']:<5}  {r['cause_if_not']}")
    print("\nManipulation check (error actually shown):")
    for c in ("A", "B"):
        sub = [r for r in rows if r["condition"] == c]
        if sub:
            n = sum(r["error_fired"] == "yes" for r in sub)
            print(f"  System {c}: {n}/{len(sub)} sessions")


def main():
    fix = DEFAULT_FIX_TIME
    if "--fix-time" in sys.argv:
        fix = sys.argv[sys.argv.index("--fix-time") + 1]
    fix_time = to_dt(fix)

    from pymongo import MongoClient
    db = MongoClient("mongodb://localhost:27017")["sds_study"]
    docs = list(db.sessions.find().sort("start_time", 1))
    if not docs:
        print("No sessions found.")
        return
    write_report([analyse(d, fix_time) for d in docs])


if __name__ == "__main__":
    main()
