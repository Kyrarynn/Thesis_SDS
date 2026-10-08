"""
Reconstructs the Rasa NLU confidence scores for every logged user turn.

Rasa's NLU (DIET) only looks at the text of the current message, not at the
dialogue history, and it is deterministic. Parsing the logged user_text again
with the SAME model file therefore gives exactly the scores the system
computed during the study.

Run in rasa_env (PowerShell, from the project folder, MongoDB running):
  python extract_nlu_confidence.py                       # newest model in models/
  python extract_nlu_confidence.py --model models\\20261002-194820-each-vocoder.tar.gz
  python extract_nlu_confidence.py --apply               # also write to MongoDB

Output: nlu_confidence.csv (one row per turn, semicolon-separated)
  intent             final intent (nlu_fallback if below the 0.7 threshold)
  top_intent         best "real" intent, also when the fallback kicked in
  confidence         confidence of top_intent
  margin             confidence difference to the 2nd intent (ambiguity)
  is_fallback        1 if the FallbackClassifier replaced the intent
  n_entities, entity_conf_mean   entities found by DIET and their mean confidence
With --apply the same values are stored per turn under turns.<i>.nlu
(the original fields stay untouched).
"""
import asyncio
import csv
import glob
import logging
import os
import sys

from pymongo import MongoClient

logging.disable(logging.WARNING)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")


def nlu_features(parse):
    ranking = [r for r in parse.get("intent_ranking", []) if r["name"] != "nlu_fallback"]
    top = ranking[0] if ranking else {"name": None, "confidence": None}
    second = ranking[1]["confidence"] if len(ranking) > 1 else 0.0
    ents = [e for e in parse.get("entities", []) if "confidence_entity" in e]
    return {
        "intent": parse["intent"]["name"],
        "top_intent": top["name"],
        "confidence": round(top["confidence"], 4) if top["confidence"] is not None else None,
        "margin": round(top["confidence"] - second, 4) if top["confidence"] is not None else None,
        "is_fallback": int(parse["intent"]["name"] == "nlu_fallback"),
        "n_entities": len(ents),
        "entity_conf_mean": round(sum(e["confidence_entity"] for e in ents) / len(ents), 4) if ents else None,
    }


async def main():
    from rasa.core.agent import Agent

    args = sys.argv
    model = args[args.index("--model") + 1] if "--model" in args else max(glob.glob("models/*.tar.gz"), key=os.path.getmtime)
    apply = "--apply" in args
    print(f"Model: {model}")
    agent = Agent.load(model)

    db = MongoClient("mongodb://localhost:27017")["sds_study"]
    rows = []
    for doc in db.sessions.find().sort("start_time", 1):
        updates = {}
        for i, turn in enumerate(doc.get("turns") or []):
            text = turn.get("user_text") or ""
            feats = nlu_features(await agent.parse_message(text))
            rows.append({"participant_code": doc.get("participant_code"),
                         "condition": doc.get("system_version"),
                         "session_id": doc["participant_id"][:8],
                         "turn": i, "user_text": text, **feats})
            updates[f"turns.{i}.nlu"] = {**feats, "model": os.path.basename(model)}
        if apply and updates:
            db.sessions.update_one({"_id": doc["_id"]}, {"$set": updates})
        print(f"  {doc.get('participant_code')} {doc.get('system_version')}: {len(updates)} turns")

    if rows:
        with open("nlu_confidence.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
            w.writeheader()
            w.writerows(rows)
    print(f"{len(rows)} turns -> nlu_confidence.csv" + ("  (+ written to MongoDB)" if apply else ""))


if __name__ == "__main__":
    asyncio.run(main())
