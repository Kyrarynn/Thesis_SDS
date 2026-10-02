"""
FastAPI router for the SASSI questionnaire.

Endpoints:
    GET  /sassi/items        -> item list + scale labels (used by sassi.html)
    POST /sassi/submit       -> store one completed questionnaire
    GET  /sassi/export.csv   -> all responses as CSV (raw items + subscale scores)

Storage: MongoDB collection "sassi_responses" in the same local database
you already use. Adjust MONGO_URI / DB_NAME below, or replace `collection`
with the client you already create in your app.
"""

import csv
import io
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from pymongo import MongoClient

from sassi_items import ITEM_IDS, ITEMS, SCALE_LABELS, SUBSCALES, score

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB", "SDS_thesis")  # <- set to DB name

_client = MongoClient(MONGO_URI)
collection = _client[DB_NAME]["sassi_responses"]

router = APIRouter(prefix="/sassi", tags=["sassi"])


class SassiSubmission(BaseModel):
    participant_id: str = Field(min_length=1, max_length=32)   # pseudonym, e.g. "P07"
    condition: Literal["A", "B"]
    session_id: str | None = None          # optional: link to your dialog session
    item_order: list[str]                  # order in which items were shown
    responses: dict[str, int]              # item_id -> 1..7

    @field_validator("responses")
    @classmethod
    def check_responses(cls, v: dict[str, int]) -> dict[str, int]:
        missing = set(ITEM_IDS) - set(v)
        extra = set(v) - set(ITEM_IDS)
        if missing:
            raise ValueError(f"Missing items: {sorted(missing)}")
        if extra:
            raise ValueError(f"Unknown items: {sorted(extra)}")
        bad = {k: val for k, val in v.items() if not 1 <= val <= 7}
        if bad:
            raise ValueError(f"Values must be 1-7: {bad}")
        return v

    @field_validator("item_order")
    @classmethod
    def check_order(cls, v: list[str]) -> list[str]:
        if sorted(v) != sorted(ITEM_IDS):
            raise ValueError("item_order must contain every item exactly once")
        return v


@router.get("/items")
def get_items():
    return {
        "scale_labels": SCALE_LABELS,
        "items": [{"id": i, "text": t} for i, t, _ in ITEMS],
    }


@router.post("/submit")
def submit(sub: SassiSubmission):
    # Prevent accidental double submission for the same participant + condition
    if collection.find_one({"participant_id": sub.participant_id, "condition": sub.condition}):
        raise HTTPException(
            status_code=409,
            detail=f"SASSI for {sub.participant_id} / condition {sub.condition} already exists",
        )
    doc = sub.model_dump()
    doc["scores"] = score(sub.responses)
    doc["submitted_at"] = datetime.now(timezone.utc)
    collection.insert_one(doc)
    return {"status": "ok", "scores": doc["scores"]}


@router.get("/export.csv")
def export_csv():
    buf = io.StringIO()
    score_cols = [f"score_{k}" for k in list(SUBSCALES) + ["TOTAL"]]
    header = ["participant_id", "condition", "session_id", "submitted_at"] + ITEM_IDS + score_cols
    writer = csv.writer(buf)
    writer.writerow(header)
    for d in collection.find().sort([("participant_id", 1), ("condition", 1)]):
        row = [
            d["participant_id"],
            d["condition"],
            d.get("session_id") or "",
            d["submitted_at"].isoformat(),
        ]
        row += [d["responses"][i] for i in ITEM_IDS]
        row += [d["scores"][k] for k in list(SUBSCALES) + ["TOTAL"]]
        writer.writerow(row)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sassi_responses.csv"},
    )
