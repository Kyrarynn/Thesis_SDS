"""
Study flow controller: decides which page a participant sees next.

Every participant runs through the same 6 steps; only the system order differs:

    step 0  demographics questionnaire
    step 1  conversation with first system
    step 2  SASSI for first system
    step 3  conversation with second system
    step 4  SASSI for second system
    step 5  done

The current step is stored in MongoDB (collection "participants"), so a page
reload or browser crash never loses the position: the start screen can resume.

Endpoints:
    POST /flow/start    {participant_number, order: "AB"|"BA"}  -> {url}
    GET  /flow/current?pid=P07                                   -> {url, step}
    POST /flow/advance  {pid, from_step}                         -> {url, step}
    GET  /flow/participants                                      -> overview for you
"""

import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB", "sds_study")

_client = MongoClient(MONGO_URI)
participants = _client[DB_NAME]["participants"]

router = APIRouter(prefix="/flow", tags=["flow"])

LAST_STEP = 5


def participant_code(number: int) -> str:
    return f"P{number:02d}"


def url_for(doc: dict) -> str:
    pid, order, step = doc["participant_id"], doc["order"], doc["step"]
    first, second = order[0], order[1]
    return {
        0: f"/static/demographics.html?pid={pid}&step=0",
        1: f"/?pid={pid}&cond={first}&step=1",
        2: f"/static/sassi.html?pid={pid}&cond={first}&step=2",
        3: f"/?pid={pid}&cond={second}&step=3",
        4: f"/static/sassi.html?pid={pid}&cond={second}&step=4",
        5: f"/static/done.html?pid={pid}",
    }[step]


class StartRequest(BaseModel):
    participant_number: int = Field(ge=1, le=999)
    order: Literal["AB", "BA"]


class AdvanceRequest(BaseModel):
    pid: str
    from_step: int


@router.post("/start")
def start(req: StartRequest):
    pid = participant_code(req.participant_number)
    if participants.find_one({"participant_id": pid}):
        raise HTTPException(409, f"{pid} already exists")
    doc = {
        "participant_id": pid,
        "participant_number": req.participant_number,
        "order": req.order,
        "step": 0,
        "created_at": datetime.now(timezone.utc),
        "step_times": {"0": datetime.now(timezone.utc)},
    }
    participants.insert_one(doc)
    return {"pid": pid, "step": 0, "url": url_for(doc)}


@router.get("/current")
def current(pid: str):
    doc = participants.find_one({"participant_id": pid})
    if not doc:
        raise HTTPException(404, f"{pid} not found")
    return {"pid": pid, "step": doc["step"], "order": doc["order"], "url": url_for(doc)}


@router.post("/advance")
def advance(req: AdvanceRequest):
    """Move to the next step. Idempotent: if the page was already completed
    (e.g. double click, reload), the participant is simply sent to the current step."""
    doc = participants.find_one({"participant_id": req.pid})
    if not doc:
        raise HTTPException(404, f"{req.pid} not found")
    if req.from_step == doc["step"] and doc["step"] < LAST_STEP:
        new_step = doc["step"] + 1
        participants.update_one(
            {"participant_id": req.pid, "step": doc["step"]},
            {"$set": {"step": new_step,
                      f"step_times.{new_step}": datetime.now(timezone.utc)}},
        )
        doc["step"] = new_step
    return {"pid": req.pid, "step": doc["step"], "url": url_for(doc)}


@router.get("/participants")
def overview():
    return [
        {"participant_id": d["participant_id"], "order": d["order"], "step": d["step"]}
        for d in participants.find().sort("participant_number", 1)
    ]
