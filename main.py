"""
FastAPI orchestration layer for the SDS user study.

Responsibilities:
- Assign participants to System A or B (researcher-controlled)
- Start Rasa sessions with the correct system_version
- Transcribe participant speech locally using Whisper (no data sent externally)
- Proxy transcribed text to Rasa
- Log all turns, timestamps, and IQ ratings to MongoDB
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
import httpx
import uuid
import logging
import tempfile
import os
import whisper
# for audio saving 
import shutil
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================

RASA_URL  = "http://localhost:5005/webhooks/rest/webhook"
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB  = "sds_study"

# Load Whisper model once at startup — "base" is fast and accurate enough
# Switch to "small" or "medium" if accuracy needs improvement
WHISPER_MODEL = whisper.load_model("base")

app = FastAPI(title="SDS Study API")

#######
# 
#######
from fastapi import Request
from fastapi.responses import JSONResponse
import traceback

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Print traceback directly to console
    print("=" * 50)
    print("CRASH DETECTED IN FASTAPI:")
    traceback.print_exc()
    print("=" * 50)
    
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": traceback.format_exc()}
    )
#######
# 
#######

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("uvicorn.error")
# logger = logging.getLogger("uvicorn")


# ============================================================
# DATABASE
# ============================================================

@app.on_event("startup")
async def startup():
    app.mongo = AsyncIOMotorClient(MONGO_URI)
    app.db    = app.mongo[MONGO_DB]
    logger.info("Connected to MongoDB")

@app.on_event("shutdown")
async def shutdown():
    app.mongo.close()


# ============================================================
# REQUEST / RESPONSE MODELS
# ============================================================

class StartSessionRequest(BaseModel):
    participant_number: int
    system_version: str    # researcher passes "A" or "B" explicitly

class MessageRequest(BaseModel):
    participant_id: str
    user_text: str

class RatingRequest(BaseModel):
    participant_id: str
    turn_index: int
    rating: int            # 1-5 IQ rating


# ============================================================
# ENDPOINTS
# ============================================================

AUDIO_DIR = Path("audio_recordings")
AUDIO_DIR.mkdir(exist_ok=True)

@app.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...),
                           participant_id: str = "",
                           turn_index: int = 0):
    """
    Receives an audio blob from the browser,
    transcribes it locally using Whisper, and returns the text.
    Saves audio per turn for analysis (OpenSMILE etc.)
    """
    suffix = ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        contents = await audio.read()
        
        # Check if received audio is non-empty
        if len(contents) == 0:
            raise HTTPException(status_code=400, detail="Empty audio recording received.")
            
        tmp.write(contents)
        tmp_path = tmp.name

    # Save permanent copy for acoustic feature extraction
    if participant_id:
        save_path = AUDIO_DIR / f"{participant_id}_turn{turn_index}.webm"
        shutil.copy(tmp_path, save_path)
        logger.info(f"Audio saved: {save_path}")

    try:
        result = WHISPER_MODEL.transcribe(
            tmp_path,
            language="en",
            fp16=False,
        )
        transcript = result.get("text", "").strip()
        logger.info(f"Whisper transcript: {transcript}")
        return {"text": transcript}
    except Exception as e:
        logger.error(f"Whisper processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Whisper error: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/session/start")
async def start_session(req: StartSessionRequest):
    """
    Called once when a participant begins the study.
    Creates a session document in MongoDB and starts a Rasa session
    with the assigned system_version.
    """
    if req.system_version not in ("A", "B"):
        raise HTTPException(status_code=400, detail="system_version must be 'A' or 'B'")

    participant_id = str(uuid.uuid4())
    start_time     = datetime.now(timezone.utc)

    session_doc = {
        "participant_id":     participant_id,
        "participant_number": req.participant_number,
        "system_version":     req.system_version,
        "start_time":         start_time,
        "end_time":           None,
        "turns":              [],
    }
    await app.db.sessions.insert_one(session_doc)

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                RASA_URL,
                json={
                    "sender":   participant_id,
                    "message":  "/session_start",
                    "metadata": {"system_version": req.system_version},
                },
                timeout=10.0,
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Rasa unreachable: {e}")

    logger.info(
        f"Session started | participant={req.participant_number} "
        f"| id={participant_id} | system={req.system_version}"
    )

    return {
        "participant_id": participant_id,
        "system_version": req.system_version,
        "start_time":     start_time.isoformat(),
    }


@app.post("/message")
async def send_message(req: MessageRequest):
    """
    Receives transcribed text, forwards to Rasa,
    logs the turn with timestamps, and returns the bot response.
    """
    turn_start = datetime.now(timezone.utc)

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

    turn_end  = datetime.now(timezone.utc)
    bot_texts = [r.get("text", "") for r in rasa_responses if r.get("text")]
    bot_text  = " ".join(bot_texts)

    turn = {
        "turn_start": turn_start,
        "turn_end":   turn_end,
        "user_text":  req.user_text,
        "bot_text":   bot_text,
        "iq_rating":  None,
    }

    await app.db.sessions.update_one(
        {"participant_id": req.participant_id},
        {"$push": {"turns": turn}},
    )

    return {
        "bot_text":   bot_text,
        "turn_start": turn_start.isoformat(),
        "turn_end":   turn_end.isoformat(),
    }


@app.post("/rating")
async def submit_rating(req: RatingRequest):
    """
    Stores the participant's IQ rating (1-5) for a specific turn.
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