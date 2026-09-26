import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.db.database import db
from app.constants.statuses import JobStatus, JobStage, is_valid_job_transition
from app.core.exceptions import JobStateError


class JobRepository:
    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self.conn = connection

    def _get_conn(self) -> sqlite3.Connection:
        return self.conn if self.conn is not None else db.get_connection()

    def create(self, job_data: dict, conn: Optional[sqlite3.Connection] = None) -> dict:
        c = conn or self._get_conn()
        sql = """
        INSERT INTO jobs (
            job_uuid, document_id, job_type, status, stage, priority,
            attempt_count, max_attempts, worker_id, created_at, started_at,
            completed_at, last_heartbeat_at, duration_ms, progress_percentage,
            processed_pages, total_pages, error_code, error_message,
            retry_after, idempotency_key, updated_at
        ) VALUES (
            :job_uuid, :document_id, :job_type, :status, :stage, :priority,
            :attempt_count, :max_attempts, :worker_id, CURRENT_TIMESTAMP, NULL,
            NULL, NULL, NULL, :progress_percentage,
            :processed_pages, :total_pages, NULL, NULL,
            NULL, :idempotency_key, CURRENT_TIMESTAMP
        );
        """
        job_data.setdefault("job_type", "PDF_EXTRACTION")
        job_data.setdefault("status", JobStatus.QUEUED.value)
        job_data.setdefault("stage", JobStage.VALIDATION.value)
        job_data.setdefault("priority", 0)
        job_data.setdefault("attempt_count", 0)
        job_data.setdefault("max_attempts", 3)
        job_data.setdefault("worker_id", None)
        job_data.setdefault("progress_percentage", 0.0)
        job_data.setdefault("processed_pages", 0)
        job_data.setdefault("total_pages", 0)
        job_data.setdefault("idempotency_key", None)

        cursor = c.cursor()
        cursor.execute(sql, job_data)
        job_id = cursor.lastrowid
        cursor.close()
        return self.get_by_id(job_id, conn=c)

    def get_by_id(self, job_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def get_by_uuid(self, job_uuid: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_uuid = ?;", (job_uuid,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def get_by_document_id(self, doc_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            "SELECT * FROM jobs WHERE document_id = ? ORDER BY id DESC LIMIT 1;",
            (doc_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def get_by_idempotency_key(self, key: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT * FROM jobs WHERE idempotency_key = ?;", (key,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def claim_next_job(self, worker_id: str) -> Optional[dict]:
        """Atomically claim the next queued or retrying job for the given worker."""
        with db.transaction() as conn:
            cursor = conn.cursor()
            # Select candidate job
            cursor.execute(
                """
                SELECT id FROM jobs
                WHERE status IN ('QUEUED', 'RETRYING')
                  AND (retry_after IS NULL OR retry_after <= CURRENT_TIMESTAMP)
                ORDER BY priority DESC, created_at ASC
                LIMIT 1;
                """
            )
            row = cursor.fetchone()
            if not row:
                cursor.close()
                return None

            job_id = row["id"]
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'RUNNING',
                    worker_id = ?,
                    started_at = COALESCE(started_at, ?),
                    last_heartbeat_at = ?,
                    attempt_count = attempt_count + 1,
                    updated_at = ?
                WHERE id = ? AND status IN ('QUEUED', 'RETRYING');
                """,
                (worker_id, now_iso, now_iso, now_iso, job_id),
            )
            if cursor.rowcount == 0:
                cursor.close()
                return None  # Another worker claimed it

            cursor.close()
            return self.get_by_id(job_id, conn=conn)

    def update_heartbeat(self, job_id: int) -> None:
        """Update last_heartbeat_at to indicate worker liveness."""
        with db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET last_heartbeat_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
                """,
                (job_id,),
            )
            cursor.close()

    def update_progress(
        self,
        job_id: int,
        processed_pages: int,
        total_pages: int,
        stage: Optional[str] = None,
    ) -> None:
        pct = (processed_pages / total_pages * 100.0) if total_pages > 0 else 0.0
        with db.connection() as conn:
            cursor = conn.cursor()
            if stage:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET processed_pages = ?,
                        total_pages = ?,
                        progress_percentage = ?,
                        stage = ?,
                        last_heartbeat_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (processed_pages, total_pages, pct, stage, job_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET processed_pages = ?,
                        total_pages = ?,
                        progress_percentage = ?,
                        last_heartbeat_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (processed_pages, total_pages, pct, job_id),
                )
            cursor.close()

    def update_status(
        self,
        job_id: int,
        status: JobStatus,
        stage: Optional[JobStage] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
        retry_after: Optional[str] = None,
    ) -> Optional[dict]:
        with db.transaction() as conn:
            curr = self.get_by_id(job_id, conn=conn)
            if not curr:
                return None

            current_status = JobStatus(curr["status"])
            if not is_valid_job_transition(current_status, status):
                raise JobStateError(
                    f"Cannot transition job {job_id} from {current_status} to {status}"
                )

            now_iso = datetime.now(timezone.utc).isoformat()
            completed_at = now_iso if status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED) else None

            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = ?,
                    stage = COALESCE(?, stage),
                    error_code = ?,
                    error_message = ?,
                    completed_at = COALESCE(?, completed_at),
                    duration_ms = COALESCE(?, duration_ms),
                    retry_after = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (
                    status.value,
                    stage.value if stage else None,
                    error_code,
                    error_message,
                    completed_at,
                    duration_ms,
                    retry_after,
                    now_iso,
                    job_id,
                ),
            )
            cursor.close()
            return self.get_by_id(job_id, conn=conn)

    def find_stale_jobs(self, stale_timeout_seconds: float) -> list[dict]:
        """Find active jobs whose heartbeat is older than timeout."""
        with db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('RUNNING', 'PROCESSING', 'OCR_PROCESSING', 'GENERATING_TEXT', 'UPLOADING')
                  AND (
                      last_heartbeat_at IS NULL
                      OR (strftime('%s', 'now') - strftime('%s', last_heartbeat_at)) > ?
                  );
                """,
                (int(stale_timeout_seconds),),
            )
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]

    def reset_stale_job(self, job_id: int, max_attempts: int = 3) -> Optional[dict]:
        with db.transaction() as conn:
            curr = self.get_by_id(job_id, conn=conn)
            if not curr:
                return None
            cursor = conn.cursor()
            if curr["attempt_count"] >= max_attempts:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = 'FAILED',
                        error_code = 'MAX_RETRIES_EXCEEDED',
                        error_message = 'Job failed after exceeding maximum heartbeat recovery attempts',
                        completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (job_id,),
                )
            else:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = 'RETRYING',
                        stage = 'recovering',
                        worker_id = NULL,
                        retry_after = datetime('now', '+5 seconds'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (job_id,),
                )
            cursor.close()
            return self.get_by_id(job_id, conn=conn)
