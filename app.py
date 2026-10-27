import asyncio
import logging
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from faster_whisper import WhisperModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("transcription-service")

APP_TITLE = "Audio Transcription API"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 100 * 1024 * 1024))
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
TRANSCRIBE_CONCURRENCY = max(1, int(os.getenv("TRANSCRIBE_CONCURRENCY", "1")))

# float32 is the safest CPU default on macOS. Override from the shell if wanted.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float32")
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "0") == "1"

app = FastAPI(title=APP_TITLE, version="1.0.0")
inference_slots = asyncio.Semaphore(TRANSCRIBE_CONCURRENCY)


@lru_cache(maxsize=1)
def get_model() -> WhisperModel:
    """Load one Whisper model per process and reuse it across requests."""
    logger.info(
        "Loading Whisper model=%s device=%s compute_type=%s",
        WHISPER_MODEL,
        WHISPER_DEVICE,
        WHISPER_COMPUTE_TYPE,
    )
    model = WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )
    logger.info("Whisper model loaded successfully")
    return model


def normalize_audio(source: Path, destination: Path) -> None:
    """Decode supported input and normalize it to 16 kHz mono PCM WAV."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is not installed or not available on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Audio decoding timed out") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        raise ValueError(f"Audio could not be decoded. FFmpeg: {stderr[:500]}") from exc


def run_transcription(audio_path: Path) -> dict:
    """Run faster-whisper and return JSON-ready output."""
    model = get_model()
    segments, info = model.transcribe(
        str(audio_path),
        vad_filter=True,
        beam_size=1,
    )

    items = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        items.append(
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": text,
            }
        )

    # Be defensive across faster-whisper versions.
    duration = getattr(info, "duration", None)
    if duration is None and items:
        duration = items[-1]["end"]
    if duration is None:
        duration = 0.0

    language_probability = getattr(info, "language_probability", None)

    return {
        "language": getattr(info, "language", None),
        "language_probability": (
            round(float(language_probability), 4)
            if language_probability is not None
            else None
        ),
        "duration_seconds": round(float(duration), 3),
        "text": " ".join(item["text"] for item in items),
        "segments": items,
    }


async def save_upload(file: UploadFile, destination: Path) -> int:
    """Stream an upload to disk so the complete file is never held in memory."""
    total = 0
    try:
        with destination.open("wb") as output:
            while True:
                block = await file.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File exceeds upload limit")
                output.write(block)
    finally:
        await file.close()
    return total


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model": WHISPER_MODEL,
        "device": WHISPER_DEVICE,
        "compute_type": WHISPER_COMPUTE_TYPE,
    }


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio type. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    with tempfile.TemporaryDirectory(prefix="transcription_") as temp_dir:
        temp_path = Path(temp_dir)
        source = temp_path / f"input{suffix}"
        normalized = temp_path / "normalized.wav"

        total = await save_upload(file, source)
        if total == 0:
            raise HTTPException(status_code=400, detail="Uploaded audio file is empty")

        logger.info("Received %s (%d bytes)", file.filename, total)

        try:
            await asyncio.to_thread(normalize_audio, source, normalized)
            logger.info("Audio normalization completed")

            async with inference_slots:
                result = await asyncio.to_thread(run_transcription, normalized)

            logger.info("Transcription completed with %d segments", len(result["segments"]))
            return result

        except HTTPException:
            raise
        except ValueError as exc:
            logger.exception("Invalid audio input")
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.exception("Runtime dependency error")
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Unexpected transcription failure")
            detail = "Transcription failed"
            if DEBUG_ERRORS:
                detail = f"Transcription failed: {type(exc).__name__}: {exc}"
            raise HTTPException(status_code=500, detail=detail) from exc
