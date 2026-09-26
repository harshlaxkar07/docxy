import sqlite3
from datetime import datetime, timezone
from typing import Optional
from app.db.database import db


class DocumentRepository:
    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self.conn = connection

    def _get_conn(self) -> sqlite3.Connection:
        return self.conn if self.conn is not None else db.get_connection()

    def create(self, doc_data: dict, conn: Optional[sqlite3.Connection] = None) -> dict:
        sql = """
        INSERT INTO documents (
            uuid, original_filename, stored_filename, file_extension,
            mime_type, file_size_bytes, file_hash, page_count, status,
            storage_provider, s3_bucket, s3_key, s3_url, uploaded_at,
            created_at, updated_at
        ) VALUES (
            :uuid, :original_filename, :stored_filename, :file_extension,
            :mime_type, :file_size_bytes, :file_hash, :page_count, :status,
            :storage_provider, :s3_bucket, :s3_key, :s3_url, :uploaded_at,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        );
        """
        doc_data.setdefault("page_count", 0)
        doc_data.setdefault("status", "UPLOADED")
        doc_data.setdefault("storage_provider", "LOCAL")
        doc_data.setdefault("s3_bucket", None)
        doc_data.setdefault("s3_key", None)
        doc_data.setdefault("s3_url", None)
        doc_data.setdefault("uploaded_at", datetime.now(timezone.utc).isoformat())

        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(sql, doc_data)
        doc_id = cursor.lastrowid
        cursor.close()
        return self.get_by_id(doc_id, conn=c)

    def get_by_id(self, doc_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT * FROM documents WHERE id = ?;", (doc_id,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def get_by_uuid(self, uuid: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT * FROM documents WHERE uuid = ?;", (uuid,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def get_by_hash(self, file_hash: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            "SELECT * FROM documents WHERE file_hash = ? ORDER BY id DESC LIMIT 1;",
            (file_hash,),
        )
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def update(self, doc_id: int, update_data: dict, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        fields = ", ".join(f"{k} = :{k}" for k in update_data.keys())
        sql = f"UPDATE documents SET {fields} WHERE id = :id;"
        params = {**update_data, "id": doc_id}
        cursor = c.cursor()
        cursor.execute(sql, params)
        cursor.close()
        return self.get_by_id(doc_id, conn=c)

    def list_documents(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        uuid: Optional[str] = None,
    ) -> list[dict]:
        sql = "SELECT * FROM documents"
        clauses: list[str] = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if uuid:
            clauses.append("uuid = ?")
            params.append(uuid)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]

    def count_documents(self, status: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) AS total FROM documents"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += ";"

        with db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            cursor.close()
            return int(row["total"]) if row else 0
