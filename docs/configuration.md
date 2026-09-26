# Configuration Reference

All settings are configured via environment variables or `.env`:

| Setting | Default | Description |
|---|---|---|
| `APP_NAME` | `PDF Extraction Service` | Application title |
| `APP_ENV` | `development` | Environment name |
| `DEBUG` | `false` | Enable verbose debug logging |
| `DATABASE_PATH` | `./data/app.db` | SQLite database file location |
| `MAX_UPLOAD_SIZE_MB` | `100` | Maximum PDF upload size in megabytes |
| `MAX_PAGES_PER_DOCUMENT` | `1000` | Maximum allowable pages per document |
| `PDF_MIN_TEXT_LENGTH` | `200` | Minimum characters threshold for native classification |
| `PDF_MIN_IMAGE_AREA_RATIO` | `0.35` | Image area ratio threshold for scanned detection |
| `AWS_ENABLED` | `false` | Enable S3 storage (`true`/`false`) |
| `AWS_REGION` | `us-east-1` | AWS S3 region |
| `AWS_ACCESS_KEY_ID` | `None` | AWS Access Key ID |
| `AWS_SECRET_ACCESS_KEY` | `None` | AWS Secret Access Key |
| `AWS_S3_BUCKET` | `pdf-processing-bucket` | AWS S3 bucket name |
| `GROQ_ENABLED` | `false` | Enable Groq Vision OCR fallback |
| `GROQ_API_KEY` | `None` | Groq API Key |
| `GROQ_MODEL` | `llama-3.2-11b-vision-preview` | Groq Vision LLM model |
| `GROQ_REQUESTS_PER_SECOND` | `1` | Rate limit: requests per second |
| `GROQ_REQUESTS_PER_MINUTE` | `20` | Rate limit: requests per minute |
| `GROQ_REQUESTS_PER_DAY` | `1000` | Rate limit: requests per day |
| `GROQ_MIN_REQUEST_GAP_SECONDS` | `2.0` | Minimum gap between consecutive OCR calls |
| `WORKER_ENABLED` | `true` | Enable background worker thread |
| `WORKER_POLL_INTERVAL_SECONDS` | `2.0` | Queue polling interval |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | `10.0` | Liveness heartbeat interval |
| `JOB_STALE_TIMEOUT_SECONDS` | `120.0` | Inactivity threshold before job is considered abandoned |
| `TXT_INCLUDE_PAGE_MARKERS` | `true` | Include `================ PAGE X ================\n` markers in TXT |
| `TXT_INCLUDE_METADATA` | `true` | Include document header metadata in TXT |
