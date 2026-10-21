# Part 2 — System Design Answers

## How would you handle concurrent uploads?

I would separate upload concurrency from transcription concurrency because they have very different resource profiles. FastAPI can accept multiple uploads concurrently, and I would stream each file to temporary/object storage instead of reading the whole file into RAM. The expensive part is model inference, so I would keep that bounded rather than allowing every upload to start a Whisper process immediately.

For the assessment implementation I use a semaphore to limit concurrent inference per process. In production I would make the API stateless, create a job for each upload, place it on Redis/SQS, and let a controlled pool of CPU/GPU workers process the queue. That gives back-pressure during traffic spikes instead of exhausting memory or GPU capacity. I would autoscale workers based on queue depth and processing latency and apply per-user/file-size limits at the API layer.

## How would you store audio and transcripts?

For this demo I use temporary local files and delete them after the request because persistence is not required and I do not want to retain user audio unnecessarily.

In production I would store audio in object storage such as S3 and keep metadata/transcript state in PostgreSQL. The database record would contain a job ID, object key, processing status, detected language, duration, timestamped segments, model/version, retry count, and audit timestamps. Large transcript JSON could either stay in PostgreSQL as JSONB or be placed in object storage with a pointer from the database, depending on size and query patterns.

I would also define a retention policy from the beginning. Audio may contain sensitive conversations, so encryption, signed URLs, access control, and automatic deletion after the agreed retention period are part of the storage design, not afterthoughts.

## How do you retry or recover failed transcriptions?

I would first distinguish retryable failures from bad input. A temporary worker crash, storage/network issue, model timeout, or recoverable GPU error can be retried. A corrupt file, empty recording, or unsupported codec should fail immediately with a clear reason.

For background jobs I would use bounded retries with exponential backoff and jitter. The job ID would be idempotent, so a retry continues or updates the same transcription rather than creating duplicates. For long audio I would persist chunk-level progress, which means if chunk 41 fails I can retry from that point instead of retranscribing the first 40 chunks.

After the retry limit, I would move the job to a failed/dead-letter state, store the error and worker/model information, and expose that state through the API for debugging or manual retry.

## How would you expose this as an API?

For the assessment, I expose a simple FastAPI endpoint: `POST /transcribe` with a multipart audio file. It returns JSON containing the full text, language, duration, and start/end timestamps for each segment. FastAPI also gives me OpenAPI documentation at `/docs`, which makes the service easy to test.

For production I would use an asynchronous job API for long recordings: `POST /v1/transcriptions` returns `202 Accepted` and a job ID, `GET /v1/transcriptions/{job_id}` returns status, and a result endpoint returns the final transcript. I would add authentication, request/file-size limits, versioned routes, idempotency keys, structured error responses, and optionally a webhook when processing finishes. Short files could still use a synchronous endpoint where the latency is acceptable.
