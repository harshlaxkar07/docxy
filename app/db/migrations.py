import sqlite3
from typing import Optional
from app.db.database import db
from app.core.logging import get_logger

logger = get_logger(__name__)

MIGRATION_SQL = """
-- 1. Documents Table
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    file_extension TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    file_hash TEXT NOT NULL,
    page_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'UPLOADED',
    storage_provider TEXT NOT NULL DEFAULT 'LOCAL',
    s3_bucket TEXT,
    s3_key TEXT,
    s3_url TEXT,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_started_at TIMESTAMP,
    processing_completed_at TIMESTAMP,
    processing_duration_ms INTEGER,
    extraction_method TEXT,
    text_character_count INTEGER DEFAULT 0,
    word_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);

-- 2. Jobs Table
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uuid TEXT NOT NULL UNIQUE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL DEFAULT 'PDF_EXTRACTION',
    status TEXT NOT NULL DEFAULT 'QUEUED',
    stage TEXT NOT NULL DEFAULT 'validation',
    priority INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    worker_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    last_heartbeat_at TIMESTAMP,
    duration_ms INTEGER,
    progress_percentage REAL DEFAULT 0.0,
    processed_pages INTEGER DEFAULT 0,
    total_pages INTEGER DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    retry_after TIMESTAMP,
    idempotency_key TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_uuid ON jobs(job_uuid);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_document_id ON jobs(document_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_last_heartbeat ON jobs(last_heartbeat_at);
CREATE INDEX IF NOT EXISTS idx_jobs_idempotency_key ON jobs(idempotency_key) WHERE idempotency_key IS NOT NULL;

-- 3. Document Pages Table
CREATE TABLE IF NOT EXISTS document_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    width REAL DEFAULT 0.0,
    height REAL DEFAULT 0.0,
    has_text BOOLEAN DEFAULT 0,
    text_length INTEGER DEFAULT 0,
    text_density REAL DEFAULT 0.0,
    image_count INTEGER DEFAULT 0,
    image_area_ratio REAL DEFAULT 0.0,
    page_type TEXT NOT NULL DEFAULT 'NATIVE_TEXT',
    extraction_method TEXT NOT NULL DEFAULT 'NATIVE',
    ocr_used BOOLEAN DEFAULT 0,
    ocr_attempt INTEGER DEFAULT 0,
    processing_time_ms INTEGER DEFAULT 0,
    text_character_count INTEGER DEFAULT 0,
    -- The page's own extracted text. Without this, a job resumed after a crash
    -- re-reads already-DONE pages as empty and regenerates a truncated TXT.
    text TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_pages_doc_page ON document_pages(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_pages_status ON document_pages(status);

-- 4. Extracted Text Table
CREATE TABLE IF NOT EXISTS extracted_text (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    character_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    text_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id)
);

CREATE INDEX IF NOT EXISTS idx_extracted_text_doc ON extracted_text(document_id);

-- 5. Output Files Table
CREATE TABLE IF NOT EXISTS output_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    file_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    s3_bucket TEXT,
    s3_key TEXT,
    s3_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_output_files_doc ON output_files(document_id);

-- 6. Job Logs Table
CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'INFO',
    stage TEXT,
    event TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_job_logs_job ON job_logs(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_job_logs_doc ON job_logs(document_id, created_at);

-- 7. API Usage Table
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    request_type TEXT NOT NULL,
    status TEXT NOT NULL,
    request_started_at TIMESTAMP,
    request_completed_at TIMESTAMP,
    response_time_ms INTEGER,
    tokens_used INTEGER DEFAULT 0,
    error_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_usage_provider ON api_usage(provider, created_at);

-- 8. Rate Limit State Table
CREATE TABLE IF NOT EXISTS rate_limit_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    key_identifier TEXT NOT NULL,
    window_type TEXT NOT NULL,
    window_start TIMESTAMP NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER NOT NULL DEFAULT 0,
    last_request_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, key_identifier, window_type, window_start)
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_lookup ON rate_limit_state(provider, key_identifier, window_type);

-- 9. Settings Table
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    value_type TEXT NOT NULL DEFAULT 'string',
    is_secret BOOLEAN DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


# Columns added after the initial schema. CREATE TABLE IF NOT EXISTS will not
# add a column to a table that already exists, so each one is applied
# separately and skipped when already present.
ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("document_pages", "text", "TEXT"),
]


def _apply_additive_columns(conn: sqlite3.Connection) -> None:
    """Add post-initial-schema columns to databases created before them."""
    for table, column, decl in ADDITIVE_COLUMNS:
        cursor = conn.cursor()
        try:
            cursor.execute(f"PRAGMA table_info({table});")
            existing = {row[1] for row in cursor.fetchall()}
            if not existing or column in existing:
                continue
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl};")
            logger.info("Added column %s.%s", table, column)
        finally:
            cursor.close()


def run_migrations(target_db: Optional[sqlite3.Connection] = None) -> None:
    """Execute SQLite schema migrations idempotently."""
    logger.info("Running database migrations...")
    if target_db:
        target_db.executescript(MIGRATION_SQL)
        _apply_additive_columns(target_db)
    else:
        with db.connection() as conn:
            conn.executescript(MIGRATION_SQL)
            _apply_additive_columns(conn)
    logger.info("Database migrations completed successfully.")
