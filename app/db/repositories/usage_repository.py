import sqlite3
from typing import Optional
from app.db.database import db


class UsageRepository:
    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self.conn = connection

    def _get_conn(self) -> sqlite3.Connection:
        return self.conn if self.conn is not None else db.get_connection()

    def record_usage(
        self,
        provider: str,
        model: str,
        job_id: Optional[int],
        document_id: Optional[int],
        request_type: str,
        status: str,
        request_started_at: str,
        request_completed_at: str,
        response_time_ms: int,
        tokens_used: int = 0,
        error_code: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        c = conn or self._get_conn()
        sql = """
        INSERT INTO api_usage (
            provider, model, job_id, document_id, request_type,
            status, request_started_at, request_completed_at,
            response_time_ms, tokens_used, error_code, created_at
        ) VALUES (
            :provider, :model, :job_id, :document_id, :request_type,
            :status, :request_started_at, :request_completed_at,
            :response_time_ms, :tokens_used, :error_code, CURRENT_TIMESTAMP
        );
        """
        cursor = c.cursor()
        cursor.execute(
            sql,
            {
                "provider": provider,
                "model": model,
                "job_id": job_id,
                "document_id": document_id,
                "request_type": request_type,
                "status": status,
                "request_started_at": request_started_at,
                "request_completed_at": request_completed_at,
                "response_time_ms": response_time_ms,
                "tokens_used": tokens_used,
                "error_code": error_code,
            },
        )
        cursor.close()

    def get_summary_stats(self) -> dict:
        with db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_requests,
                    SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as successful_requests,
                    SUM(CASE WHEN status != 'SUCCESS' THEN 1 ELSE 0 END) as failed_requests,
                    SUM(tokens_used) as total_tokens,
                    AVG(response_time_ms) as avg_latency_ms
                FROM api_usage;
                """
            )
            row = cursor.fetchone()
            cursor.close()
            return dict(row) if row else {}
