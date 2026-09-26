import sqlite3
from typing import Optional
from app.db.database import db


class ResultRepository:
    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self.conn = connection

    def _get_conn(self) -> sqlite3.Connection:
        return self.conn if self.conn is not None else db.get_connection()

    def save_extracted_text(
        self,
        document_id: int,
        job_id: Optional[int],
        text: str,
        character_count: int,
        word_count: int,
        text_hash: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> dict:
        c = conn or self._get_conn()
        sql = """
        INSERT INTO extracted_text (
            document_id, job_id, text, character_count, word_count,
            text_hash, created_at, updated_at
        ) VALUES (
            :document_id, :job_id, :text, :character_count, :word_count,
            :text_hash, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT(document_id) DO UPDATE SET
            job_id = excluded.job_id,
            text = excluded.text,
            character_count = excluded.character_count,
            word_count = excluded.word_count,
            text_hash = excluded.text_hash,
            updated_at = CURRENT_TIMESTAMP;
        """
        cursor = c.cursor()
        cursor.execute(
            sql,
            {
                "document_id": document_id,
                "job_id": job_id,
                "text": text,
                "character_count": character_count,
                "word_count": word_count,
                "text_hash": text_hash,
            },
        )
        cursor.close()
        return self.get_extracted_text(document_id, conn=c)

    def get_extracted_text(self, document_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT * FROM extracted_text WHERE document_id = ?;", (document_id,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def save_output_file(
        self,
        document_id: int,
        job_id: Optional[int],
        file_type: str,
        filename: str,
        mime_type: str,
        file_size_bytes: int,
        s3_bucket: Optional[str] = None,
        s3_key: Optional[str] = None,
        s3_url: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> dict:
        c = conn or self._get_conn()
        sql = """
        INSERT INTO output_files (
            document_id, job_id, file_type, filename, mime_type,
            file_size_bytes, s3_bucket, s3_key, s3_url, created_at
        ) VALUES (
            :document_id, :job_id, :file_type, :filename, :mime_type,
            :file_size_bytes, :s3_bucket, :s3_key, :s3_url, CURRENT_TIMESTAMP
        );
        """
        cursor = c.cursor()
        cursor.execute(
            sql,
            {
                "document_id": document_id,
                "job_id": job_id,
                "file_type": file_type,
                "filename": filename,
                "mime_type": mime_type,
                "file_size_bytes": file_size_bytes,
                "s3_bucket": s3_bucket,
                "s3_key": s3_key,
                "s3_url": s3_url,
            },
        )
        file_id = cursor.lastrowid
        cursor.close()
        return self.get_output_file_by_id(file_id, conn=c)

    def get_output_file_by_id(self, file_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT * FROM output_files WHERE id = ?;", (file_id,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def get_output_file_by_type(
        self,
        document_id: int,
        file_type: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[dict]:
        """Most recent artifact of a given type, e.g. EXTRACTED_TXT.

        Downloads must resolve the key that was actually written rather than
        recomputing a date-partitioned one, which would miss the file as soon
        as the month rolls over.
        """
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            "SELECT * FROM output_files WHERE document_id = ? AND file_type = ? ORDER BY id DESC LIMIT 1;",
            (document_id, file_type),
        )
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def get_output_files(self, document_id: int, conn: Optional[sqlite3.Connection] = None) -> list[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            "SELECT * FROM output_files WHERE document_id = ? ORDER BY id ASC;",
            (document_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in rows]
