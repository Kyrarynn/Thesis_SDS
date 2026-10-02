"""
FastAPI router for the demographic questionnaire.

Integration in your existing app (e.g. main.py):

    from demographics_router import router as demographics_router
    app.include_router(demographics_router)

Endpoints:
    POST /demographics/submit       -> store answers for one participant
    GET  /demographics/export.csv   -> all answers as CSV

Storage: MongoDB collection "demographics" in the same database as the SASSI.
"""

import csv
import io
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB", "sds_study")

_client = MongoClient(MONGO_URI)
collection = _client[DB_NAME]["demographics"]

router = APIRouter(prefix="/demographics", tags=["demographics"])

Gender = Literal["female", "male", "non_binary", "self_describe", "prefer_not_to_say"]
Proficiency = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]
Usage = Literal["never", "rarely", "monthly", "weekly", "daily"]
Field_ = Literal[
    "computer_science_engineering",
    "natural_sciences_math",
    "social_sciences_humanities",
    "economics_law",
    "other",
    "prefer_not_to_say",
]

FIELDS = [
    "participant_id", "age", "gender", "gender_self_describe", "native_language",
    "english_proficiency", "voice_assistant_usage", "background", "submitted_at",
]


class Demographics(BaseModel):
    participant_id: str = Field(min_length=1, max_length=32)
    age: int = Field(ge=18, le=99)
    gender: Gender
    gender_self_describe: str | None = Field(default=None, max_length=100)
    native_language: str = Field(min_length=1, max_length=60)
    english_proficiency: Proficiency
    voice_assistant_usage: Usage
    background: Field_

    @model_validator(mode="after")
    def clean_self_describe(self):
        if self.gender != "self_describe":
            self.gender_self_describe = None
        self.native_language = self.native_language.strip()
        return self


@router.post("/submit")
def submit(d: Demographics):
    if collection.find_one({"participant_id": d.participant_id}):
        raise HTTPException(409, f"Demographics for {d.participant_id} already exist")
    doc = d.model_dump()
    doc["submitted_at"] = datetime.now(timezone.utc)
    collection.insert_one(doc)
    return {"status": "ok"}


@router.get("/export.csv")
def export_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(FIELDS)
    for d in collection.find().sort("participant_id", 1):
        w.writerow([
            d["submitted_at"].isoformat() if k == "submitted_at" else (d.get(k) or "")
            for k in FIELDS
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=demographics.csv"},
    )
