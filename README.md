# docxy — PDF Extraction & OCR Service

> A self-contained FastAPI service that ingests PDFs, extracts text page-by-page with PyMuPDF, falls back to Groq Vision OCR only for scanned pages, and tracks every job in SQLite with crash recovery and persistent rate limiting.

**Status:** Working prototype (~75% complete) · **Frontend:** Yes — zero-build web UI served at `/` · **Stack:** FastAPI + SQLite (WAL) + PyMuPDF · **Tests:** 22 passing · **Version control:** None (no `.git`)

---

## What this does

Turning a PDF into text is easy when the PDF is digital and hard when it is a scan. Most real documents are a mix: a contract with typed clauses and a photographed signature page, a report with native text and a scanned appendix. Running OCR over the whole file is slow and expensive; running native extraction over the whole file silently loses the scanned pages.

docxy solves this with a **native-first, per-page** pipeline. A caller `POST`s a PDF and immediately gets back a `document_id` and a `job_id` (HTTP 202) — the HTTP request does not wait for processing. A background worker thread then claims the job, classifies every page as `NATIVE_TEXT`, `IMAGE_BASED`, `MIXED` or `EMPTY` using character count, text density and image-area ratio, extracts native pages with PyMuPDF, and only sends genuinely image-based pages to the Groq Vision API. The client polls `GET /api/v1/jobs/{job_id}` for status, stage and page progress, then fetches the aggregated text.

Everything that matters is in the database, not in memory. Jobs move through an enforced state machine, write a heartbeat as each page completes, and checkpoint per-page status — so a killed process does not lose the work already done, and a startup sweep resets jobs whose heartbeat went stale. A persistent multi-window rate limiter (per second / minute / hour / day, plus a minimum gap between calls) lives in SQLite and survives restarts, so the Groq quota is respected across process boundaries.

The intended user is a backend or platform engineer who needs a document pipeline without standing up Celery, Redis or Postgres. The whole thing is SQLite plus one in-process daemon thread. Both external services are optional and degrade cleanly: with `AWS_ENABLED=false` files go to the local filesystem, and with `GROQ_ENABLED=false` image-based pages simply keep whatever native text they had. The defaults run fully offline.

## Where it lives

**Absolute path:** `/home/choice/Documents/docxy`

Not a copy or version of any sibling project. The only adjacent PDF-related directory, `/home/choice/Documents/ocr`, is unrelated in both stack and purpose (a Roboflow inference script plus an Excel exporter — no FastAPI, no SQLite, no shared modules). No other directory under `~/Documents` shares this package layout.

There is **no `.git` directory**, so there is no branch, history or remote to compare against. Every source file carries an mtime of 2026-08-27 (13:20–15:00), i.e. the project was produced in a single session and has not been touched since.

## Architecture

```
                    HTTP client (curl / Postman / your app)
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │  FastAPI  (app/main.py)                              │
        │  correlation-ID middleware → X-Request-ID            │
        │  3 exception handlers → uniform error envelope       │
        │  routers: health · documents · jobs · settings       │
        └───────────────┬──────────────────────────────────────┘
                        │ POST /api/v1/documents (multipart)
                        ▼
        ┌──────────────────────────────────────────────────────┐
        │  DocumentService.process_upload                      │
        │  1. size / extension / %PDF- magic bytes             │
        │  2. PyMuPDF structural validation (encrypted, pages) │
        │  3. SHA-256 → duplicate?  Idempotency-Key → match?   │
        │  4. write original to storage                        │
        │  5. BEGIN IMMEDIATE: insert document + job, COMMIT   │
        └───────────────┬──────────────────────────────────────┘
                        │ 202 Accepted {document_id, job_id}
                        ▼                          ┌──────────────┐
                 (returns at once)                 │  SQLite WAL  │
                                                   │  9 tables    │
        ┌──────────────────────────────────────┐   │ data/app.db  │
        │ BackgroundWorker daemon thread       │◄─►└──────────────┘
        │ (app/workers/worker.py)              │          ▲
        │  startup: recover_stale_jobs()       │          │
        │  loop: claim_next_job() every 2s     │          │
        │        BEGIN IMMEDIATE + guarded     │          │
        │        UPDATE ... WHERE status IN    │          │
        │        ('QUEUED','RETRYING')         │          │
        └───────────────┬──────────────────────┘          │
                        ▼                                 │
        ┌──────────────────────────────────────────────┐  │
        │ TaskProcessor.process_job                    │──┘
        │  temp dir ─ fetch original ─ re-validate     │
        │  init document_pages rows                    │
        │  for each page:                              │
        │    classify ──► NATIVE_TEXT / MIXED ─► PyMuPDF
        │            └──► IMAGE_BASED ─► render 150dpi JPEG
        │                                  │           │
        │    heartbeat + progress per page │           │
        │  aggregate TXT ─ extracted_text ─ output_files
        │  job → DONE / FAILED + job_logs entry        │
        └───────────────┬──────────────────┬───────────┘
                        │                  │
                        ▼                  ▼
            ┌───────────────────┐   ┌──────────────────────┐
            │ Storage           │   │ Groq Vision API      │
            │ S3 (boto3) or     │   │ via RateLimiter      │
            │ local ./data/output│  │ (SQLite-backed) +    │
            │ documents/YYYY/MM/ │  │ retry w/ backoff     │
            │ extracted/YYYY/MM/ │  │ logged to api_usage  │
            └───────────────────┘   └──────────────────────┘
                                     (off by default)
```

**Request path walkthrough**

1. `POST /api/v1/documents` reads the whole upload into memory, then `DocumentService.process_upload` validates size → extension → `%PDF-` header → PyMuPDF structure (rejects encrypted, zero-page, or over `MAX_PAGES_PER_DOCUMENT`).
2. SHA-256 of the bytes is looked up in `documents.file_hash`; a matching *completed* document short-circuits and returns the prior job with `is_duplicate: true`. An `Idempotency-Key` header is looked up in `jobs.idempotency_key` and returns the prior job.
3. The original is written to storage, then the `documents` and `jobs` rows are inserted inside one `BEGIN IMMEDIATE` transaction, so a failure never leaves an orphan job. The route returns `202` with both UUIDs.
4. The worker thread polls every `WORKER_POLL_INTERVAL_SECONDS`. `JobRepository.claim_next_job` selects a candidate and then runs a guarded `UPDATE ... WHERE id = ? AND status IN ('QUEUED','RETRYING')` inside `BEGIN IMMEDIATE`; `rowcount == 0` means someone else got it, so it returns `None`.
5. `TaskProcessor.process_job` runs the pipeline inside a temp-dir context, bumping `last_heartbeat_at` and `processed_pages` as each page finishes, and transitions the job through `RUNNING → PROCESSING → DONE` (or `FAILED`, with a `job_logs` row).
6. On startup, `RecoveryService.recover_stale_jobs()` finds jobs whose `last_heartbeat_at` is older than `JOB_STALE_TIMEOUT_SECONDS` and resets them to `RETRYING` (`retry_after = now + 5s`), or `FAILED` with `MAX_RETRIES_EXCEEDED` past `JOB_MAX_ATTEMPTS`.

## Project structure

```
docxy/
├── run.py                        # uvicorn entry point; reads HOST/PORT/DEBUG/LOG_LEVEL from settings
├── requirements.txt              # 13 deps, all floor-pinned with >=, no lockfile
├── tailwind.config.js            # recipe for regenerating app/static/css/tailwind.css
├── .env.example                  # every setting with its default; credential fields blank
├── .gitignore                    # covers data/output, data/*.db, logs — NOT data/test_output
├── app/
│   ├── main.py                   # FastAPI app, lifespan (migrations + worker), CORS, middleware, 3 error handlers
│   ├── static/                   # web UI, served by StaticFiles at / (no build step)
│   │   ├── index.html            # shell: workspace, documents, detail, service views
│   │   ├── favicon.svg
│   │   ├── fonts/                # self-hosted Inter + JetBrains Mono (variable woff2)
│   │   ├── css/
│   │   │   ├── docxy.css         # design tokens + component layer (light/dark)
│   │   │   ├── fonts.css         # @font-face for the bundled fonts
│   │   │   ├── tailwind.css      # pre-built utilities (generated; committed)
│   │   │   └── tailwind.src.css  # build input — see tailwind.config.js
│   │   └── js/                   # api.js (REST client), ui.js (format/icons), app.js (router, polling)
│   ├── api/routes/
│   │   ├── documents.py          # list, upload, get, text, pages, download
│   │   ├── jobs.py               # status, logs, retry, cancel
│   │   ├── health.py             # /health, /health/live, /health/ready
│   │   └── settings.py           # read-only echo of non-secret config
│   ├── core/
│   │   ├── config.py             # pydantic-settings Settings + ensure_directories()
│   │   ├── logging.py            # rotating file logs + SecretMaskingFilter
│   │   └── exceptions.py         # AppException hierarchy
│   ├── constants/
│   │   ├── statuses.py           # DocumentStatus, JobStatus, JobStage, PageType + VALID_JOB_TRANSITIONS
│   │   └── errors.py             # ErrorCode enum used in the error envelope
│   ├── db/
│   │   ├── database.py           # sqlite3 connection(), transaction(), PRAGMAs
│   │   ├── migrations.py         # single idempotent CREATE TABLE IF NOT EXISTS script (9 tables)
│   │   └── repositories/         # 7 hand-written repositories (document, job, page, result, log, usage, rate_limit)
│   ├── services/
│   │   ├── document_service.py   # upload validation, dedup, idempotency, atomic insert
│   │   ├── pdf_service.py        # validate_pdf, inspect_and_classify_page, render_page_to_image
│   │   ├── extraction_service.py # per-page native-vs-OCR decision and persistence
│   │   ├── txt_service.py        # aggregate pages into the final TXT + hash
│   │   ├── vision_provider.py    # VisionProvider ABC
│   │   ├── groq_service.py       # Groq implementation; records every call to api_usage
│   │   ├── rate_limiter.py       # persistent multi-window limiter in rate_limit_state
│   │   ├── s3_service.py         # S3 or local-filesystem storage, canonical keys, presigned URLs
│   │   ├── job_service.py        # status/logs/retry/cancel used by the jobs router
│   │   └── temp_manager.py       # per-job temp directory context manager
│   ├── workers/
│   │   ├── worker.py             # BackgroundWorker daemon thread + polling loop
│   │   ├── task_processor.py     # the end-to-end pipeline (the heart of the project)
│   │   └── recovery.py           # stale-heartbeat sweep
│   ├── schemas/                  # common.py, document.py, job.py, settings.py (Pydantic v2)
│   └── utils/                    # hashing.py (SHA-256), file_utils.py (magic bytes), retry.py (backoff+jitter)
├── tests/
│   ├── conftest.py               # forces test DB/dirs; builds real PDFs at runtime with PyMuPDF
│   ├── unit/                     # hashing, validation, classification, rate limiter, state machine
│   ├── integration/              # test_pipeline.py, test_api.py, test_recovery.py
│   └── performance/              # 10- and 50-page benchmark, asserts <100ms/page
├── docs/                         # 8 markdown docs (architecture, api, database, pipeline, config, worker, rate-limiting, recovery)
├── openspec/changes/pdf-processing-system/
│   ├── proposal.md, design.md, tasks.md   # 40/40 tasks marked done
│   └── specs/                    # 6 capability specs
├── data/                         # app.db (WAL), output/, temp/, test_output/ (62 stray test artifacts)
└── logs/                         # application.log, worker.log, error.log, audit.log (rotating)
```

~4,100 lines of application code, ~490 lines of tests.

## Tech stack

| Layer | Technology | Notes |
|---|---|---|
| Web framework | FastAPI + Uvicorn (standard) | 4 routers, 12 endpoints; auto Swagger at `/docs`, ReDoc at `/redoc` |
| Validation / schemas | Pydantic v2, pydantic-settings | `Settings` loads `.env`, `extra="ignore"` |
| PDF engine | PyMuPDF (`fitz`) | Structural validation, per-page text + image inspection, page rendering |
| Image handling | Pillow | Resizes rendered pages to 1600px, encodes JPEG q=85 |
| Database | SQLite 3 (stdlib `sqlite3`) | WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`, autocommit + explicit `BEGIN IMMEDIATE` |
| Data access | Hand-written repository layer | No ORM, no SQLAlchemy, no Alembic — raw SQL in 7 repositories |
| Background work | `threading.Thread` daemon in-process | No Celery, no Redis, no external broker |
| Object storage | boto3 / AWS S3 | Optional; local-filesystem fallback is a real implementation, not a stub |
| Vision OCR | `groq` Python SDK | Optional; behind a `VisionProvider` ABC so it can be swapped |
| Uploads | python-multipart | Required by FastAPI for `UploadFile` |
| Tests | pytest, pytest-asyncio, httpx / FastAPI `TestClient` | 21 tests, ~0.9s |
| Process / spec workflow | OpenSpec (`openspec/`) | Spec-driven change record; documentation only, not runtime |

## Frontend

A **zero-build web UI** lives in `app/static/` and is mounted by `app/main.py` with
`StaticFiles(html=True)` at `/`. The mount is registered *after* every router, so
`/api/v1/*`, `/health*` and `/docs` keep precedence; if the directory is missing the
service logs a warning and serves the API alone.

There is no bundler, no `package.json` and no install step — `python run.py` serves both
the API and the UI on the same port. The page is plain ES modules plus a design-token
stylesheet.

**Nothing is fetched from a CDN.** Tailwind's utility classes are pre-built into a 3 KB
`app/static/css/tailwind.css`, and Inter + JetBrains Mono are self-hosted as variable
woff2 in `app/static/fonts/` (172 KB, latin + latin-ext). Verified by loading the UI
with every non-localhost request blocked: no external requests, no errors, correct
typography. The build is only needed if you add new Tailwind classes:

```bash
npx tailwindcss@3.4.17 -c tailwind.config.js \
  -i app/static/css/tailwind.src.css -o app/static/css/tailwind.css --minify
```

| Path | View | What it does |
|------|------|--------------|
| `/#/` | Workspace | Drag-and-drop upload, live service readiness, in-flight job cards, recent documents |
| `/#/documents` | Ledger | All documents, status filters, pagination |
| `/#/doc/<uuid>` | Detail | Spec rail, **page map**, extracted text viewer, TXT/PDF download, job log |
| `/#/service` | Service | Effective config from `/api/v1/settings` + `/health/ready` |

**How it tracks work.** The UI never holds job state of its own: it polls
`GET /api/v1/documents`, which joins each document with its latest job. One request
covers every in-flight job, so progress for N documents costs one poll, not N. The
interval adapts — 1.2 s while anything is running, 12 s when idle, and polling pauses
entirely in a hidden tab. Because all state is server-side, a browser refresh mid-job
loses nothing; this is the property the API was designed for, now actually demonstrated.

**The page map.** The document detail view renders one cell per page, coloured by the
classifier's actual decision (`GET /api/v1/documents/{id}/pages`): blue for `NATIVE_TEXT`
read straight from the text layer, amber for `IMAGE_BASED` that cost a vision call, a
split cell for `MIXED`, a dashed outline for `EMPTY`, and a red border on any page that
failed. A 20-page contract with five scanned pages is legible at a glance, which is the
whole premise of the pipeline made visible. Per-page rows are fetched only on this view,
one document at a time — the workspace deliberately does not, since that would turn a
single list poll into one request per in-flight document.

**Design.** Minimalist/Swiss — hairline rules, a strict grid, uppercase micro-labels,
Inter for text and JetBrains Mono for machine values (UUIDs, hashes, counts). The palette
is slate + a single "scan blue" accent, plus one amber reserved for the OCR path. The
in-flight card renders one cell per PDF page that fills as the worker checkpoints, making
the pipeline visible as it runs. Colour is never the only carrier: every cell has a
title naming its page, type and status, and the legend and counts repeat it in text.
Verified at 0 axe-core WCAG 2.1 AA violations across all four views in both themes.
The generated design system is recorded in `design-system/docxy/MASTER.md`.

Swagger UI (`/docs`) and ReDoc (`/redoc`) remain available and unchanged.

## API / Interface

All routes verified present in `app/api/routes/`. Successful responses are wrapped as `{"success": true, "data": {...}}`; every error path (including validation errors and unhandled exceptions) returns `{"success": false, "error": {"code", "message", "request_id", "details"}}`. Every response carries `X-Request-ID` and `X-Response-Time-Ms` headers.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/documents` | Upload a PDF (multipart field `file`). Returns `202` with `document_id`, `job_id`, `status`, `is_duplicate`. Honors an `Idempotency-Key` request header. |
| `GET` | `/api/v1/documents/{document_id}` | Document metadata (filename, size, hash, page count, status, storage keys, timings). |
| `GET` | `/api/v1/documents/{document_id}/text` | The aggregated extracted text for a completed document. |
| `GET` | `/api/v1/documents/{document_id}/download?file_type=pdf\|txt` | Download the original PDF or the generated TXT. Redirects to a presigned URL when S3 is on; serves the file directly otherwise. See *Known issues* — the `txt` branch is broken across month boundaries. |
| `GET` | `/api/v1/jobs/{job_id}` | Job status, stage, `progress_percentage`, `processed_pages`/`total_pages`, `duration_ms`, error fields. |
| `GET` | `/api/v1/jobs/{job_id}/logs?limit=&offset=` | Paged lifecycle/audit log entries for the job (`limit` 1–500, default 100). |
| `POST` | `/api/v1/jobs/{job_id}/retry` | Re-queue a job in `FAILED` or `RETRYING`. |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Cancel a queued or active job; rejected for terminal states. |
| `GET` | `/api/v1/settings` | Echo of non-secret configuration (limits, thresholds, feature flags, worker settings). Read-only. |
| `GET` | `/health` | App name and environment. |
| `GET` | `/health/live` | Liveness probe. |
| `GET` | `/health/ready` | Readiness: DB `SELECT 1`, worker running flag, storage mode (`s3`/`local`), vision mode. |

Example upload response:

```json
{
  "success": true,
  "data": {
    "document_id": "8f3b25d0-994c-4e89-9831-50e501a3512b",
    "job_id": "4a28f731-92b1-4f11-9f93-1579292837bc",
    "status": "queued",
    "is_duplicate": false,
    "message": "Document uploaded and processing job queued"
  }
}
```

There is **no authentication on any endpoint**. There is no CLI beyond `run.py`.

## Data & storage

**Engine:** SQLite 3 via the Python standard library. Connections are opened with `check_same_thread=False` and `isolation_level=None` (autocommit); `app/db/database.py` sets `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, and exposes `connection()` plus a `transaction()` context manager doing `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`.

**Migrations:** one idempotent `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` script (`MIGRATION_SQL` in `app/db/migrations.py`), executed from the FastAPI lifespan on every start. There is no versioned migration history, no downgrade path, and no Alembic. Schema changes to existing tables would have to be applied by hand.

| Table | Holds |
|---|---|
| `documents` | UUID, original/stored filename, mime, size, SHA-256 `file_hash` (indexed), page count, status, storage provider + S3 bucket/key/url, timings, char/word counts |
| `jobs` | `job_uuid`, FK to document, status, stage, priority, `attempt_count`/`max_attempts`, `worker_id`, `last_heartbeat_at` (indexed), progress, error code/message, `retry_after`, `idempotency_key` (partial index) |
| `document_pages` | Per-page metrics: dimensions, `text_length`, `text_density`, `image_count`, `image_area_ratio`, `page_type`, `extraction_method`, `ocr_used`, status. **No column for the page's text.** Unique on `(document_id, page_number)` |
| `extracted_text` | The full aggregated text, char/word counts, `text_hash`. Unique on `document_id` |
| `output_files` | One row per produced artifact (`ORIGINAL_PDF`, `EXTRACTED_TXT`) with its real `s3_key` |
| `job_logs` | Structured lifecycle events per job/document (`level`, `stage`, `event`, `message`, `metadata_json`) |
| `api_usage` | Every vision-provider call: provider, model, status (`SUCCESS`/`RATE_LIMITED`/`TIMEOUT`/`ERROR`), latency, tokens |
| `rate_limit_state` | Persistent counters per provider/key/window; unique on `(provider, key_identifier, window_type, window_start)` |
| `settings` | Created but **never read or written** by any code |

The live `data/app.db` exists and contains all 9 tables with zero rows in every one.

**File storage:** `S3Service` writes to S3 when `AWS_ENABLED=true`, otherwise to `LOCAL_STORAGE_DIR` using the same key layout. Canonical keys are date-partitioned: `documents/YYYY/MM/<uuid>/original.pdf` and `extracted/YYYY/MM/<uuid>/extracted.txt`. The upload path additionally writes a flat copy at `LOCAL_STORAGE_DIR/<doc_uuid>_<filename>.pdf`, which is what the worker reads back and what the `file_type=pdf` download serves.

## Configuration

All settings are read by `app/core/config.py` from environment variables or a `.env` file. **Every variable has a working default — none is strictly required to start the service.** The ones marked "required *if enabled*" must be set only when you turn on the corresponding feature.

| Variable | Default | Purpose | Required |
|---|---|---|---|
| `APP_NAME` | `PDF Extraction Service` | Title shown in `/docs` and `/health` | No |
| `APP_ENV` | `development` | Environment label | No |
| `DEBUG` | `false` | Enables uvicorn reload via `run.py` | No |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind address | No |
| `DATABASE_PATH` | `./data/app.db` | SQLite file location | No |
| `MAX_UPLOAD_SIZE_MB` | `100` | Upload size limit (checked after the body is in RAM) | No |
| `MAX_PAGES_PER_DOCUMENT` | `1000` | Rejects larger PDFs at validation | No |
| `PDF_MIN_TEXT_LENGTH` | `200` | Chars at/above which a page counts as text-bearing | No |
| `PDF_MIN_TEXT_DENSITY` | `0.005` | Chars per unit page area threshold | No |
| `PDF_MIN_IMAGE_AREA_RATIO` | `0.35` | Image coverage at/above which a text page becomes `MIXED` | No |
| `AWS_ENABLED` | `false` | Switches storage from local filesystem to S3 | No |
| `AWS_REGION` | `us-east-1` | S3 region | If AWS enabled |
| `AWS_ACCESS_KEY_ID` | *(empty)* | S3 credential; omit to use the ambient boto3 chain | If AWS enabled |
| `AWS_SECRET_ACCESS_KEY` | *(empty)* | S3 credential | If AWS enabled |
| `AWS_S3_BUCKET` | `pdf-processing-bucket` | Target bucket | If AWS enabled |
| `S3_PRESIGNED_EXPIRATION_SECONDS` | `3600` | Presigned download URL lifetime | No |
| `LOCAL_STORAGE_DIR` | `./data/output` | Storage root when AWS is off | No |
| `GROQ_ENABLED` | `false` | Enables the Vision OCR fallback | No |
| `GROQ_API_KEY` | *(empty)* | Groq credential | If Groq enabled |
| `GROQ_MODEL` | `llama-3.2-11b-vision-preview` | Vision model id — **see Known issues** | No |
| `GROQ_REQUESTS_PER_SECOND` | `1` | Rate-limit window | No |
| `GROQ_REQUESTS_PER_MINUTE` | `20` | Rate-limit window | No |
| `GROQ_REQUESTS_PER_HOUR` | `500` | Rate-limit window | No |
| `GROQ_REQUESTS_PER_DAY` | `1000` | Rate-limit window | No |
| `GROQ_MIN_REQUEST_GAP_SECONDS` | `2` | Enforced minimum spacing between calls | No |
| `GROQ_MAX_RETRIES` | `3` | Retries for rate-limit/timeout errors only | No |
| `GROQ_TIMEOUT_SECONDS` | `30.0` | Per-call timeout | No |
| `WORKER_ENABLED` | `true` | Starts the background thread from the lifespan | No |
| `WORKER_COUNT` | `1` | Read but **not honored** — exactly one worker starts | No |
| `WORKER_POLL_INTERVAL_SECONDS` | `2` | Idle poll delay | No |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | `10` | Declared; no timer thread uses it | No |
| `JOB_STALE_TIMEOUT_SECONDS` | `120` | Heartbeat age after which recovery reclaims a job | No |
| `JOB_MAX_ATTEMPTS` | `3` | Attempts before a recovered job is failed permanently | No |
| `TXT_INCLUDE_PAGE_MARKERS` | `true` | Writes `==== PAGE n ====` separators into the TXT | No |
| `TXT_INCLUDE_METADATA` | `true` | Writes a metadata header block into the TXT | No |
| `LOG_LEVEL` | `INFO` | Log level (also passed to uvicorn by `run.py`) | No |
| `LOG_TO_DATABASE` | `true` | Mirrors job events into `job_logs` | No |
| `LOG_DIR` | `./logs` | Rotating log destination | No |

No secrets are committed: there is no `.env` file in the tree, and `.env.example` ships blank credential placeholders.

## Getting started

A working virtualenv already exists at `/home/choice/Documents/docxy/.venv` (Python 3.12) with all dependencies installed. To use it directly, skip to step 4.

```bash
# 1. Enter the project
cd "/home/choice/Documents/docxy"

# 2. Create and activate a virtualenv (Python 3.10+; 3.12 is what is installed here)
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Optional: create a .env. Every setting has a working default,
#    so the service runs correctly with no .env at all.
cp .env.example .env

# 5. Run. No separate migration command is needed — migrations run
#    automatically from the FastAPI lifespan on every start.
python run.py
# equivalently:
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On startup the app creates `./data`, `./data/temp`, `./data/output` and `./logs`, applies the SQLite schema to `./data/app.db`, runs the stale-job recovery sweep, and starts the background worker thread. Interactive docs: <http://localhost:8000/docs>.

With the defaults (`AWS_ENABLED=false`, `GROQ_ENABLED=false`) it runs fully offline: originals and extracted TXT go to `./data/output`, and image-based pages are left with whatever native text they contain.

**Smoke test**

```bash
curl -F "file=@some.pdf" http://localhost:8000/api/v1/documents
curl http://localhost:8000/api/v1/jobs/<job_id>
curl http://localhost:8000/api/v1/documents/<document_id>/text
curl http://localhost:8000/health/ready
```

**Tests**

```bash
# 21 unit + integration tests; verified passing in 0.89s
"/home/choice/Documents/docxy/.venv/bin/python" -m pytest tests/unit tests/integration -q

# add the performance benchmark (asserts <100ms per page)
"/home/choice/Documents/docxy/.venv/bin/python" -m pytest -q
```

`tests/conftest.py` forces `DATABASE_PATH=./data/test_app.db`, `WORKER_ENABLED=false`, `LOCAL_STORAGE_DIR=./data/test_output` and `TEMP_DIR=./data/test_temp`, and builds real PDFs at runtime with PyMuPDF. It deletes the test database afterwards but **not** the files written under `data/test_output/`.

**Docker:** none. There is no `Dockerfile`, no `docker-compose.yml`, no `pyproject.toml` and no CI configuration.

**Further documentation:** `docs/architecture.md`, `docs/api.md`, `docs/database.md`, `docs/processing-pipeline.md`, `docs/configuration.md`, `docs/worker.md`, `docs/rate-limiting.md`, `docs/recovery.md`.

## What is complete

- [x] **Upload validation chain** — empty-file, `MAX_UPLOAD_SIZE_MB`, extension, `%PDF-` magic bytes, then PyMuPDF structural checks (encrypted, zero-page, `MAX_PAGES_PER_DOCUMENT`) — all before anything is persisted
- [x] **SHA-256 duplicate detection** against the indexed `documents.file_hash`, returning the prior completed document/job with `is_duplicate: true`
- [x] **Idempotency-Key** lookup against `jobs.idempotency_key` (partial index), covered by a passing HTTP test
- [x] **Atomic document + job creation** inside `db.transaction()` (`BEGIN IMMEDIATE`), so a partial upload never leaves an orphan job row
- [x] **Full 9-table SQLite schema** with indexes, applied idempotently at startup and verified present in the live `data/app.db`
- [x] **Atomic job claiming** — candidate `SELECT` plus a guarded `UPDATE ... WHERE status IN ('QUEUED','RETRYING')` inside `BEGIN IMMEDIATE`, returning `None` on `rowcount == 0` so two workers cannot double-claim
- [x] **Enforced job state machine** — `VALID_JOB_TRANSITIONS` checked on every `update_status`, raising `JobStateError` on illegal moves (unit-tested)
- [x] **End-to-end pipeline** in `task_processor.py` — temp dir, fetch original, re-validate, optional S3 upload, page-table init, per-page loop with progress + heartbeat, TXT aggregation, `extracted_text` upsert, `output_files` row, `DONE` transition, and a full failure branch that marks the document `FAILED` and writes a `job_logs` entry
- [x] **Page classification heuristic** producing `NATIVE_TEXT` / `IMAGE_BASED` / `MIXED` / `EMPTY` from character count, text density and image-area ratio against configurable thresholds — unit-tested for all three main classes
- [x] **Native-first extraction** — native pages go through PyMuPDF only; `IMAGE_BASED` pages render to a 150-dpi JPEG (thumbnailed to 1600px) and call the vision provider, with OCR failure falling back to whatever native text exists rather than failing the page
- [x] **Persistent multi-window rate limiter** — per-second/minute/hour/day counters plus a minimum request gap, stored in `rate_limit_state`, surviving restarts; auto-sleeps or raises `GroqRateLimitError` with `retry_after` (unit-tested)
- [x] **Groq vision provider behind a `VisionProvider` ABC**, recording every call outcome into `api_usage` with tokens and latency, wrapped in exponential-backoff-with-jitter retry for rate-limit and timeout errors only
- [x] **Crash recovery** — jobs with a stale `last_heartbeat_at` are reset to `RETRYING` (`retry_after = now + 5s`) or `FAILED` past `JOB_MAX_ATTEMPTS` (integration-tested by backdating a heartbeat 300s)
- [x] **Storage abstraction** with date-partitioned canonical keys, boto3 presigned URLs, and a real local-filesystem fallback
- [x] **Secret-masking log pipeline** — regex filters for `gsk_*`, `AKIA*`, bearer tokens and `api_key=...` applied to the rotating `application.log` / `worker.log` / `error.log` / `audit.log`
- [x] **Uniform response envelope + correlation IDs** — three exception handlers all emit `{success, error:{code, message, request_id, details}}`; every response carries `X-Request-ID` and `X-Response-Time-Ms`
- [x] **Working test suite** — 21 tests in `tests/unit` and `tests/integration`, verified passing in 0.89s, including a genuine upload → worker → extraction → TXT → download integration test
- [x] **Documentation** — 8 files in `docs/` plus a complete OpenSpec change with proposal, design, 6 capability specs and 40/40 tasks marked done

## What is missing / incomplete

- [ ] **Per-page extracted text is never persisted, so resumed jobs silently produce truncated output.** `document_pages` has no text column, and `ExtractionService.extract_page` returns the bare page record (no `"text"` key) when it skips an already-`DONE` page. `TXTService.format_document_text` reads `page.get("text", "")`, so every page completed before a crash contributes an empty body to the regenerated TXT. `tests/integration/test_recovery.py::test_page_checkpoint_resumption` only asserts page *statuses*, never the text, so it passes anyway. This is the single most important defect.
- [ ] **`GET /api/v1/documents/{id}/download?file_type=txt` breaks across month boundaries.** The route rebuilds the key with `s3_service.generate_canonical_key()`, which uses `datetime.now()` — so a download in a later month looks under `extracted/<current YYYY/MM>/...` and misses the file. The real key is stored in `output_files.s3_key`, but the route never reads it. Its local fallback path (`LOCAL_STORAGE_DIR/<stem>_extracted.txt`) is never written by the pipeline (the TXT is written into the temp dir, which is deleted), so this degrades to a hard 404.
- [ ] **No authentication, authorization or per-client quota** on any endpoint.
- [ ] **Upload is not streamed.** `documents.upload_document` does `await file.read()` on the whole body, so `MAX_UPLOAD_SIZE_MB=100` is enforced only after 100 MB is already in RAM.
- [ ] **No version control.** There is no `.git` directory, so ~4,100 lines of application code have no history, no remote and no backup.
- [ ] **No packaging or deployment story** — no `Dockerfile`, no `docker-compose.yml`, no `pyproject.toml`, no CI config, no systemd unit or process manager, despite the project describing itself as production-grade.
- [ ] **The Groq OCR path is never executed by any test.** `conftest.py` forces `GROQ_ENABLED=false`, no test injects a fake `VisionProvider`, and no test uses `sample_image_pdf_bytes` for extraction (only for classification). The whole OCR fallback, usage recording and retry path is unverified code. S3 mode is likewise untested (no `moto`).
- [ ] **`recover_stale_jobs()` runs only once**, inside `BackgroundWorker.start()`. The polling loop never re-sweeps, so a job orphaned while the process keeps running stays stuck until the app restarts.
- [ ] **Heartbeats are bumped once per page**, not on an independent timer thread. A single OCR page slower than `JOB_STALE_TIMEOUT_SECONDS` (default 120s) makes a healthy job look stale to the recovery sweep — contradicting the "periodic heartbeat" language in `docs/recovery.md` and the unused `WORKER_HEARTBEAT_INTERVAL_SECONDS` setting.
- [ ] **`s3_service.generate_presigned_url` returns a dead link when AWS is off** — it hands back `/api/v1/storage/local/{s3_key}`, but no storage router exists (only health, documents, jobs and settings are registered).
- [ ] **The `settings` table is created but never used.** There is no settings repository, and `GET /api/v1/settings` only echoes environment config. The runtime-configurable settings implied by the schema — including per-request custom Groq keys, which `task_processor.process_job` accepts as `custom_groq_key` but no route ever supplies — are not wired up.
- [ ] **`WORKER_COUNT` is not honored.** `app/main.py` starts exactly one module-level worker singleton; multiple workers are unimplemented (the claim logic would support it).
- [ ] **No graceful signal handling.** `app/workers/worker.py` imports `signal` and `sys` but never installs a handler; shutdown happens only through the FastAPI lifespan.
- [ ] **`app/schemas/result.py` does not exist** despite being listed as delivered in OpenSpec task 7.3 (only `common.py`, `document.py`, `job.py`, `settings.py` are present).
- [ ] **`docs/worker.md` does not match the code** — it documents the atomic claim as a single `UPDATE ... WHERE id = (SELECT ...)`; the code does a separate `SELECT` then a guarded `UPDATE` inside `BEGIN IMMEDIATE`. Equivalent in effect under SQLite, but the doc is wrong.

## Known issues & risks

**Correctness**

- `GROQ_MODEL` defaults to `llama-3.2-11b-vision-preview` in both `app/core/config.py` and `.env.example`. That is a Groq *preview* model that has since been retired, so the OCR path will fail with a model-not-found error against the current Groq API until this is pointed at a supported vision model.
- `document_service.process_upload` writes the original PDF to `LOCAL_STORAGE_DIR` *before* the DB transaction, so a failed insert leaves an orphaned file on disk with no cleanup.
- `tests/unit/test_classification.py` line 14 is a tautology — `assert analysis.has_text if hasattr(...) else analysis.character_count > 0`, and `PDFPageAnalysis` has no `has_text` attribute — so that assertion never tests what it appears to.

**Security**

- **No secrets are committed.** There is no `.env` file in the tree; `.env.example` ships empty `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `GROQ_API_KEY` placeholders, and a scan for `sk-*` / `gsk_*` / `AKIA*` patterns across the tree found nothing.
- CORS is configured with `allow_origins=["*"]` together with `allow_credentials=True` in `app/main.py` — a combination browsers reject outright, and a bad default for anything public.
- No authentication on any endpoint, combined with the full-body `await file.read()`: a handful of concurrent 100 MB uploads can exhaust RAM.

**Supply chain and hygiene**

- Every dependency in `requirements.txt` is floor-pinned with `>=` and there is no lockfile, so a fresh install picks up whatever `groq` / `boto3` / `fastapi` majors exist today. The Groq SDK in particular has a moving surface.
- No git repository at all — the entire codebase is untracked.
- `data/test_output/` holds 62 test-run artifacts (UUID-named PDFs and `extracted/2026/08/...` and `extracted/2026/09/...` text files), and `data/app.db` sits in the working tree. `.gitignore` covers `data/output/*` and `data/*.db` but **not** `data/test_output`, so these would be committed the moment the project is initialized as a repo. Running the test suite adds more each time.

## Next steps

1. **`git init` and commit.** Before anything else — 4,100 lines with no history is the largest single risk here. Add `data/test_output/` and `data/test_temp/` to `.gitignore` first, and delete the 62 existing artifacts under `data/test_output/`.
2. **Fix the resumption text-loss bug.** Add a `text` column to `document_pages` (or an `extracted_page_text` table), write it in `ExtractionService.extract_page`, and read it back on the skip-if-`DONE` branch. Then extend `test_page_checkpoint_resumption` to assert the *content* of the regenerated TXT, not just page statuses.
3. **Fix the TXT download.** Read `output_files.s3_key` for the document's `EXTRACTED_TXT` row instead of recomputing the key from `datetime.now()`, and either register the `/api/v1/storage/local/...` router that `generate_presigned_url` advertises or have it return a usable path.
4. **Update `GROQ_MODEL` to a currently supported Groq vision model** in `config.py` and `.env.example`, then add the first test that actually exercises the OCR path by injecting a fake `VisionProvider` into `ExtractionService` — that unblocks verification of the retry, rate-limit and `api_usage` code as well.
5. **Add a minimum viable security baseline** — an API key or bearer-token dependency on the `documents` and `jobs` routers, a real CORS origin list, and streaming upload with an early size cutoff instead of `await file.read()`.
6. **Make recovery continuous.** Call `recover_stale_jobs()` on an interval inside the polling loop, and move the heartbeat onto its own timer thread driven by `WORKER_HEARTBEAT_INTERVAL_SECONDS` so a slow OCR page is not mistaken for a dead worker.
7. **Add a deployment story** — a `Dockerfile` and `docker-compose.yml`, a `pyproject.toml` or a pinned `requirements.lock`, and a CI job that runs `pytest`. Then reconcile `docs/worker.md` with the actual claim implementation.
