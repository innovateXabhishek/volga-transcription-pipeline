# Volga Partners — Audio Transcription Pipeline

A small production-minded transcription service built for the Volga Partners AI Engineer assessment.

It accepts common audio files, normalizes them with FFmpeg, transcribes speech locally with `faster-whisper`, and returns both the full transcript and segment-level timestamps as JSON.

## Architecture

```text
Client
  |
  | multipart audio upload
  v
FastAPI /transcribe
  |
  | validate + stream to temporary storage
  v
FFmpeg normalization
  |  (mono, 16 kHz PCM WAV)
  v
faster-whisper + VAD
  |
  | segment text + timestamps
  v
Structured JSON response
```

## Why these choices?

- **Python + FastAPI**: small amount of code, good request validation, automatic OpenAPI/Swagger docs, and a stack I have used for AI/backend services.
- **faster-whisper**: local speech-to-text, segment timestamps, language detection, and no paid transcription dependency for the assessment.
- **FFmpeg**: reliable format/codec decoding and one consistent model input format.
- **VAD**: avoids spending inference time on long silent regions.
- **Temporary files**: keeps this demo simple and avoids retaining user audio by default.
- **Bounded inference concurrency**: Whisper inference is compute-heavy, so requests are not allowed to start an unlimited number of model runs in one process.
- **Pinned PyAV compatibility**: `faster-whisper==1.2.1` is paired with `av>=11,<19` because PyAV 19 removed an argument still used by that faster-whisper release.

## Supported formats

- WAV
- MP3
- M4A
- FLAC
- OGG
- WebM

Regardless of the source codec, FFmpeg converts the recording to **16 kHz mono PCM WAV** before transcription.

## Run locally

### 1. Prerequisites

- Python 3.10+
- FFmpeg installed and available on `PATH`
- Internet access on the first run so the selected Whisper model can be downloaded

### 2. Create the environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows:

```powershell
.venv\Scripts\activate
```

### 3. Start the API

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open the interactive API documentation at:

```text
http://127.0.0.1:8000/docs
```

### 4. Transcribe a file

Using Swagger UI: open `/docs` → `POST /transcribe` → **Try it out** → choose an audio file → **Execute**.

Or with cURL:

```bash
curl -X POST "http://127.0.0.1:8000/transcribe" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@sample.mp3"
```

## Example response

```json
{
  "language": "en",
  "language_probability": 0.9874,
  "duration_seconds": 8.42,
  "text": "Hello everyone. This is a quick transcription test.",
  "segments": [
    {"start": 0.48, "end": 2.16, "text": "Hello everyone."},
    {"start": 2.32, "end": 5.91, "text": "This is a quick transcription test."}
  ]
}
```

## Handling concurrent uploads

Uploads are streamed to temporary files in 1 MB blocks rather than being loaded completely into memory. FFmpeg and Whisper run outside the async event loop so FastAPI remains responsive. Model inference is protected by a configurable semaphore (`TRANSCRIBE_CONCURRENCY`, default `1`) because CPU/GPU inference is the expensive resource.

In production, I would run multiple isolated transcription workers and put long-running jobs behind a queue such as Redis + Celery/RQ. The API layer remains stateless and can scale independently.

## Storage design

This assessment deletes temporary audio automatically after each request. That is intentional: the core requirement does not require retention, and retaining recordings creates privacy and lifecycle concerns.

For a production system I would store original/normalized audio in object storage such as S3 and save transcript metadata in PostgreSQL. A transcript record would contain fields such as `job_id`, object key, status, language, duration, timestamps/segments, model version, retry count, and created/updated timestamps. Retention policies or deletion jobs would control how long audio remains available.

## Retry and recovery

I would classify failures into retryable and non-retryable cases:

- **Retryable:** transient storage/network errors, temporary worker failure, GPU out-of-memory after worker recovery, model service timeout.
- **Non-retryable:** corrupt audio, unsupported codec, empty input, validation failure.

Queued jobs would use bounded retries with exponential backoff and jitter. Each job would have an idempotent ID so a retry updates the same job instead of creating duplicate transcript records. After the retry limit, the job would move to a failed/dead-letter state with the error reason recorded for debugging.

## Long audio

The demo endpoint is synchronous because it keeps the assessment easy to run. `faster-whisper` performs internal segmentation and VAD, so longer files can still be processed, but holding an HTTP request open for a 60–90 minute recording is not how I would ship it at scale.

For production I would:

1. Upload directly to object storage.
2. Create a transcription job and return `202 Accepted` with a job ID.
3. Process audio in background workers.
4. Chunk long recordings into manageable windows (for example 30–60 seconds), with a small overlap where needed.
5. Add each chunk's original offset to its segment timestamps.
6. Merge overlapping text carefully to avoid duplicated words.
7. Persist progress so a failed worker can resume rather than restarting an hour-long file.

## API shape for a production version

```text
POST /v1/transcriptions           -> create job / upload reference
GET  /v1/transcriptions/{job_id}  -> status + metadata
GET  /v1/transcriptions/{job_id}/result -> transcript + segments
DELETE /v1/transcriptions/{job_id} -> delete transcript/audio according to policy
GET  /health                      -> liveness
```

For small files, a synchronous `/transcribe` endpoint like the implementation in this repository is also useful for local tools and low-volume use cases.

## Configuration

```text
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=float32
TRANSCRIBE_CONCURRENCY=1
MAX_UPLOAD_BYTES=104857600
```

For this Mac/CPU demo I use `WHISPER_COMPUTE_TYPE=float32` for compatibility. For GPU deployment I would switch `WHISPER_DEVICE=cuda` and benchmark the best model/compute type for the available GPU.

## What I would monitor in production

- end-to-end processing latency
- queue wait time
- real-time factor (processing time / audio duration)
- failure and retry rate
- upload size / duration distribution
- CPU/GPU and memory utilization
- empty or low-confidence transcription rate
- model/version used for every transcript

I would evaluate transcription quality separately using representative recordings and WER/CER where ground-truth transcripts are available.

## Scope / trade-offs

I intentionally kept the submitted implementation small. It demonstrates the requested flow—file input, format normalization, transcription, and segment timestamps—without hiding the important logic behind a large framework.

Production concerns such as authentication, object storage, Redis/Celery, database persistence, webhooks, speaker diarization, rate limiting, and distributed tracing are described above but are not required to run the core assessment.
