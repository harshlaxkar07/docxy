# Database Schema & Persistence

The application uses SQLite3 configured with **Write-Ahead Logging (WAL)** for high concurrency and resilience:
- `PRAGMA journal_mode = WAL;`
- `PRAGMA foreign_keys = ON;`
- `PRAGMA synchronous = NORMAL;`
- `PRAGMA busy_timeout = 5000;`

---

## Relational Tables

### 1. `documents`
Tracks all uploaded PDF documents and high-level extraction metrics.
- `id` (INTEGER PRIMARY KEY)
- `uuid` (TEXT UNIQUE)
- `original_filename` (TEXT)
- `stored_filename` (TEXT)
- `file_extension` (TEXT)
- `mime_type` (TEXT)
- `file_size_bytes` (INTEGER)
- `file_hash` (TEXT, Indexed) - SHA-256 for duplicate detection
- `page_count` (INTEGER)
- `status` (TEXT) - `UPLOADED`, `PROCESSING`, `COMPLETED`, `FAILED`
- `storage_provider` (TEXT) - `S3` or `LOCAL`
- `s3_bucket`, `s3_key`, `s3_url`
- `uploaded_at`, `processing_started_at`, `processing_completed_at`, `processing_duration_ms`
- `extraction_method` (`NATIVE`, `HYBRID_OCR`)
- `text_character_count`, `word_count`

### 2. `jobs`
State machine task queue for asynchronous worker execution.
- `id` (INTEGER PRIMARY KEY)
- `job_uuid` (TEXT UNIQUE)
- `document_id` (INTEGER FK -> documents.id)
- `status` (TEXT) - `QUEUED`, `RUNNING`, `PROCESSING`, `OCR_PROCESSING`, `DONE`, `FAILED`, `RETRYING`, `CANCELLED`
- `stage` (TEXT) - `validation`, `page_inspection`, `native_extraction`, `ocr_processing`, `txt_generation`, `completed`
- `attempt_count`, `max_attempts`
- `worker_id` (TEXT)
- `last_heartbeat_at` (TIMESTAMP) - Updated periodically for liveness
- `progress_percentage`, `processed_pages`, `total_pages`
- `error_code`, `error_message`
- `retry_after` (TIMESTAMP)
- `idempotency_key` (TEXT)

### 3. `document_pages`
Page-level checkpointing table enabling granular resumability.
- `id` (INTEGER PRIMARY KEY)
- `document_id` (INTEGER FK)
- `page_number` (INTEGER)
- `width`, `height`, `text_length`, `text_density`, `image_count`, `image_area_ratio`
- `page_type` (`NATIVE_TEXT`, `IMAGE_BASED`, `MIXED`, `EMPTY`)
- `extraction_method` (`NATIVE`, `OCR_GROQ`, `NONE`)
- `ocr_used` (BOOLEAN)
- `status` (`PENDING`, `PROCESSING`, `DONE`, `FAILED`)
- `UNIQUE(document_id, page_number)`

### 4. `extracted_text`
Aggregated final extraction result.
- `document_id`, `job_id`, `text`, `character_count`, `word_count`, `text_hash`

### 5. `output_files`
Catalog of original and generated artifacts.
- `document_id`, `job_id`, `file_type`, `filename`, `s3_bucket`, `s3_key`, `s3_url`

### 6. `job_logs`
Task lifecycle and audit event logs.
- `job_id`, `document_id`, `level`, `stage`, `event`, `message`, `metadata_json`

### 7. `api_usage`
External API audit tracking without secret leakage.
- `provider`, `model`, `job_id`, `document_id`, `response_time_ms`, `tokens_used`, `status`

### 8. `rate_limit_state`
Multi-window persistent sliding rate limiter state.
- `provider`, `key_identifier`, `window_type`, `window_start`, `request_count`, `token_count`, `last_request_at`
