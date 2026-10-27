# Audio Transcription Service

A small FastAPI service that accepts audio files, normalizes them with FFmpeg, transcribes speech with `faster-whisper`, and returns timestamped segments as JSON.

## Features

- WAV, MP3, M4A, FLAC, OGG and WebM input
- streamed uploads with a configurable size limit
- FFmpeg normalization to 16 kHz mono PCM WAV
- language detection and segment-level timestamps
- voice activity detection
- bounded transcription concurrency
- automatic cleanup of temporary files
- Docker support

## Request flow

```text
audio upload
    |
    v
FastAPI /transcribe
    |
    v
validate + stream to temporary file
    |
    v
FFmpeg normalization
    |
    v
faster-whisper
    |
    v
JSON response with transcript + timestamps
```

## Requirements

- Python 3.10+
- FFmpeg available on `PATH`

On macOS:

```bash
brew install ffmpeg
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the service:

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Interactive API documentation is available at:

```text
http://127.0.0.1:8000/docs
```

## Usage

```bash
curl -X POST "http://127.0.0.1:8000/transcribe" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@sample.mp3"
```

Example response:

```json
{
  "language": "en",
  "language_probability": 0.9874,
  "duration_seconds": 8.42,
  "text": "Hello everyone. This is a quick transcription test.",
  "segments": [
    {
      "start": 0.48,
      "end": 2.16,
      "text": "Hello everyone."
    },
    {
      "start": 2.32,
      "end": 5.91,
      "text": "This is a quick transcription test."
    }
  ]
}
```

## Configuration

The service can be configured with environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `WHISPER_MODEL` | `small` | transcription model |
| `WHISPER_DEVICE` | `cpu` | inference device |
| `WHISPER_COMPUTE_TYPE` | `float32` | compute type |
| `TRANSCRIBE_CONCURRENCY` | `1` | simultaneous transcription jobs per process |
| `MAX_UPLOAD_BYTES` | `104857600` | upload size limit |
| `DEBUG_ERRORS` | `0` | include internal exception details in HTTP 500 responses |

## Design notes

### Audio handling

Uploads are written to disk in 1 MB blocks so the complete file is never held in memory. FFmpeg handles container and codec differences and converts every supported input into the same format before transcription.

### Model lifecycle

The transcription model is loaded once per process and reused across requests. This avoids paying model initialization cost on every request.

### Concurrency

FFmpeg and transcription are blocking workloads, so both are moved off the event loop. A semaphore limits concurrent transcription jobs to prevent a single process from exhausting CPU or GPU memory.

### Long recordings

The current endpoint is synchronous and works well for small and medium recordings. For long-running workloads, the next step would be an asynchronous job API with object storage and background workers. Large files can be processed in chunks while preserving timestamp offsets, and chunk progress can be persisted for recovery.

### Storage and retries

Temporary files are deleted automatically after each request. A production deployment that needs retention would store source audio in object storage and transcript metadata in a database. Transient infrastructure failures should use bounded retries; invalid or corrupted audio should fail without retrying.

## Docker

```bash
docker build -t transcription-service .
docker run --rm -p 8000:8000 transcription-service
```

Then open `http://127.0.0.1:8000/docs`.
