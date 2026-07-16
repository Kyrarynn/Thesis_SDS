# Important: INSTALLATIONS NEEDED:
# pip install faster-whisper fastapi uvicorn soundfile
# Also install ffmpeg (macOS: brew install ffmpeg | Ubuntu: sudo apt-get install ffmpeg)

from faster_whisper import WhisperModel
from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn, tempfile, shutil, os, traceback

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

class Health(BaseModel):
    ok: bool

@app.get("/ping", response_model=Health)
def ping():  # quick health check
    return {"ok": True}

# smaller models are faster; please use "tiny" or "base" if CPU is slow
model = WhisperModel("small", compute_type="int8")  

@app.post("/transcribe")
async def transcribe(file: UploadFile):
    tmp_path = None
    try:
        # save upload to a temp file with extension (helps ffmpeg)
        suffix = os.path.splitext(file.filename)[-1] or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        segments, info = model.transcribe(tmp_path, vad_filter=True, beam_size=1)
        text = " ".join(s.text for s in segments).strip()
        return {"text": text}
    except Exception as e:
        traceback.print_exc()
        return {"text": "", "error": str(e)}
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)