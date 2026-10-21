# 3–4 minute screen-recording script

The notes below are intentionally conversational. Do not read them too quickly; speak as if you are explaining your code to another engineer.

## 0:00–0:25 — Show the repository / README title

**Say:**

Hi, I’m Abhishek. For this assessment I built a small audio transcription API using Python, FastAPI, FFmpeg and faster-whisper. I kept the core implementation intentionally simple: accept an audio file, normalize it into a consistent format, transcribe it locally, and return both the complete text and segment-level timestamps as JSON.

## 0:25–0:55 — Scroll to the README architecture diagram

**Say:**

The flow is upload, validation, FFmpeg normalization, Whisper inference, and then a structured response. I chose faster-whisper because it gives me local inference and timestamps without requiring a paid API for the demo. I use FFmpeg because audio files can have different containers, codecs, channels and sample rates, so I prefer converting everything to mono 16 kilohertz PCM before it reaches the model.

## 0:55–1:35 — Open `app.py`; point at `save_upload`, supported extensions and `normalize_audio`

**Say:**

On the input side, I stream the upload to a temporary file in one-megabyte blocks instead of loading the entire recording into memory. There is a size limit and a supported-format check. Then this normalization function calls FFmpeg. Keeping preprocessing separate from inference is useful when debugging because I can distinguish a decoding problem from an STT problem.

## 1:35–2:10 — Point at `run_transcription` and returned segment fields

**Say:**

This is the actual transcription step. The Whisper model is loaded once per process and reused. I enable voice activity detection so we avoid spending inference time on long silent regions. For every returned segment I keep the start time, end time and text, and then I also join the segments into a full transcript. I’m keeping timestamps as numeric seconds because that is easier for downstream services such as subtitles, search, meeting analysis or another NLP pipeline.

## 2:10–2:45 — Point at `asyncio.to_thread` and semaphore

**Say:**

One thing I wanted to be careful about is concurrency. FastAPI is asynchronous, but FFmpeg and model inference are blocking and compute-heavy. I run those operations off the event loop, and I use a bounded semaphore around inference. I would rather apply back-pressure than let a traffic spike start an unlimited number of Whisper runs and exhaust CPU or GPU memory.

## 2:45–3:25 — Go back to README sections “Long audio”, “Retry and recovery”, and “Storage design”

**Say:**

For production, especially for long audio, I would not keep an HTTP request open for an hour-long recording. I would upload the audio to object storage, create a job, put that job on a queue, and have dedicated transcription workers process it. Long recordings can be chunked with small overlaps, and each chunk’s offset is added back to its timestamps. I would persist chunk progress so a failure can resume instead of starting again from zero.

I would store audio in object storage and transcript metadata in PostgreSQL, with a clear retention policy because recordings can contain sensitive information. Retries would only happen for transient errors and would use exponential backoff; invalid or corrupt audio would fail immediately.

## 3:25–3:55 — Open `http://127.0.0.1:8000/docs`, expand POST `/transcribe`, upload your sample audio, execute, then show the JSON result

**Say:**

Finally, this is the API running locally. I can select an MP3 or WAV file here, execute the request, and the response contains the detected language, duration, full text and timestamped segments. I’ve kept the implementation small enough to review quickly, but the boundaries are there to scale the API, storage and inference workers independently if this were moved into production. Thank you.

## Recording tip

Use a normal speaking pace. Leave a short pause when you change files or scroll. If the first model download makes the demo slow, run one transcription before starting the recording so the model is already cached.
