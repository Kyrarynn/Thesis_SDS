"""
FastAPI orchestration layer for the SDS user study.

Responsibilities:
- Assign participants to System A or B (counterbalanced)
- Start Rasa sessions with the correct system_version
- Proxy messages between the UI and Rasa
- Log all turns, timestamps, and IQ ratings to MongoDB
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
import httpx
import uuid
import logging

# ============================================================
# CONFIG
# ============================================================

RASA_URL = "http://localhost:5005/webhooks/rest/webhook"
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB  = "sds_study"

app = FastAPI(title="SDS Study API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("uvicorn")

# ============================================================
# DATABASE
# ============================================================

@app.on_event("startup")
async def startup():
    app.mongo = AsyncIOMotorClient(MONGO_URI)
    app.db = app.mongo[MONGO_DB]
    logger.info("Connected to MongoDB")

@app.on_event("shutdown")
async def shutdown():
    app.mongo.close()


# ============================================================
# COUNTERBALANCING
# Simple alternating assignment: odd participant numbers → A,
# even → B. Replace with a proper randomisation list for the
# actual study if needed.
# ============================================================

def assign_system_version(participant_number: int) -> str:
    return "A" if participant_number % 2 != 0 else "B"


# ============================================================
# REQUEST / RESPONSE MODELS
# ============================================================

class StartSessionRequest(BaseModel):
    participant_number: int          # sequential number assigned by researcher

class MessageRequest(BaseModel):
    participant_id: str
    user_text: str                   # transcribed speech from Web Speech API

class RatingRequest(BaseModel):
    participant_id: str
    turn_index: int                  # which exchange is being rated (0-indexed)
    rating: int                      # 1–5 IQ rating


# ============================================================
# ENDPOINTS
# ============================================================

@app.post("/session/start")
async def start_session(req: StartSessionRequest):
    """
    Called once when a participant begins the study.
    Creates a session document in MongoDB and starts a Rasa session
    with the assigned system_version.
    """
    participant_id = str(uuid.uuid4())
    system_version = assign_system_version(req.participant_number)
    start_time = datetime.now(timezone.utc)

    # Create session document
    session_doc = {
        "participant_id":     participant_id,
        "participant_number": req.participant_number,
        "system_version":     system_version,
        "start_time":         start_time,
        "end_time":           None,
        "turns":              [],
    }
    await app.db.sessions.insert_one(session_doc)

    # Start Rasa session with system_version in metadata
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                RASA_URL,
                json={
                    "sender":   participant_id,
                    "message":  "/session_start",
                    "metadata": {"system_version": system_version},
                },
                timeout=10.0,
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Rasa unreachable: {e}")

    logger.info(
        f"Session started | participant={req.participant_number} "
        f"| id={participant_id} | system={system_version}"
    )

    return {
        "participant_id": participant_id,
        "system_version": system_version,
        "start_time":     start_time.isoformat(),
    }


@app.post("/message")
async def send_message(req: MessageRequest):
    """
    Receives transcribed user speech, forwards to Rasa,
    logs the turn with timestamps, and returns the bot response.
    """
    turn_start = datetime.now(timezone.utc)

    # Forward to Rasa
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                RASA_URL,
                json={"sender": req.participant_id, "message": req.user_text},
                timeout=15.0,
            )
            rasa_responses = response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Rasa unreachable: {e}")

    turn_end = datetime.now(timezone.utc)

    # Extract bot text from Rasa response list
    bot_texts = [r.get("text", "") for r in rasa_responses if r.get("text")]
    bot_text  = " ".join(bot_texts)

    # Build turn document
    turn = {
        "turn_start":   turn_start,
        "turn_end":     turn_end,
        "user_text":    req.user_text,
        "bot_text":     bot_text,
        "iq_rating":    None,          # filled in by /rating endpoint
    }

    # Append turn to session document
    await app.db.sessions.update_one(
        {"participant_id": req.participant_id},
        {"$push": {"turns": turn}},
    )

    return {
        "bot_text":     bot_text,
        "turn_start":   turn_start.isoformat(),
        "turn_end":     turn_end.isoformat(),
    }


@app.post("/rating")
async def submit_rating(req: RatingRequest):
    """
    Stores the participant's IQ rating (1–5) for a specific turn.
    Called immediately after the participant submits their rating
    following each exchange.
    """
    if not 1 <= req.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    result = await app.db.sessions.update_one(
        {"participant_id": req.participant_id},
        {"$set": {f"turns.{req.turn_index}.iq_rating": req.rating}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"status": "ok", "turn_index": req.turn_index, "rating": req.rating}


@app.post("/session/end")
async def end_session(participant_id: str):
    """
    Marks the session as complete with an end timestamp.
    Called when the conversation ends or the participant finishes.
    """
    end_time = datetime.now(timezone.utc)

    result = await app.db.sessions.update_one(
        {"participant_id": participant_id},
        {"$set": {"end_time": end_time}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info(f"Session ended | id={participant_id}")
    return {"status": "ok", "end_time": end_time.isoformat()}


@app.get("/session/{participant_id}")
async def get_session(participant_id: str):
    """
    Returns the full session log for a participant.
    Useful for inspection and data export.
    """
    session = await app.db.sessions.find_one(
        {"participant_id": participant_id},
        {"_id": 0},
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ============================================================
# SERVE UI
# ============================================================

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    with open("static/index.html") as f:
        return f.read()
