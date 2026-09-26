import json
import sqlite3
from typing import Optional, Any
from app.db.database import db


class LogRepository:
    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self.conn = connection

    def _get_conn(self) -> sqlite3.Connection:
        return self.conn if self.conn is not None else db.get_connection()

    def create_log(
        self,
        job_id: Optional[int],
        document_id: Optional[int],
        level: str,
        event: str,
        message: str,
        stage: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        c = conn or self._get_conn()
        sql = """
        INSERT INTO job_logs (
            job_id, document_id, level, stage, event, message, metadata_json, created_at
        ) VALUES (
            :job_id, :document_id, :level, :stage, :event, :message, :metadata_json, CURRENT_TIMESTAMP
        );
        """
        metadata_str = json.dumps(metadata) if metadata else None
        cursor = c.cursor()
        cursor.execute(
            sql,
            {
                "job_id": job_id,
                "document_id": document_id,
                "level": level.upper(),
                "stage": stage,
                "event": event,
                "message": message,
                "metadata_json": metadata_str,
            },
        )
        cursor.close()

    def get_logs_by_job(
        self,
        job_id: int,
        limit: int = 100,
        offset: int = 0,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            """
            SELECT * FROM job_logs
            WHERE job_id = ?
            ORDER BY id ASC
            LIMIT ? OFFSET ?;
            """,
            (job_id, limit, offset),
        )
        rows = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in rows]

    def get_logs_by_document(
        self,
        document_id: int,
        limit: int = 100,
        offset: int = 0,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            """
            SELECT * FROM job_logs
            WHERE document_id = ?
            ORDER BY id ASC
            LIMIT ? OFFSET ?;
            """,
            (document_id, limit, offset),
        )
        rows = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in rows]
