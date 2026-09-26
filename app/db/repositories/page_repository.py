import sqlite3
from typing import Optional
from app.db.database import db
from app.constants.statuses import PageStatus


class PageRepository:
    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self.conn = connection

    def _get_conn(self) -> sqlite3.Connection:
        return self.conn if self.conn is not None else db.get_connection()

    def create_batch(self, pages_data: list[dict], conn: Optional[sqlite3.Connection] = None) -> None:
        c = conn or self._get_conn()
        sql = """
        INSERT OR IGNORE INTO document_pages (
            document_id, page_number, width, height, has_text, text_length,
            text_density, image_count, image_area_ratio, page_type,
            extraction_method, ocr_used, ocr_attempt, processing_time_ms,
            text_character_count, status, error_code, error_message,
            created_at, updated_at
        ) VALUES (
            :document_id, :page_number, :width, :height, :has_text, :text_length,
            :text_density, :image_count, :image_area_ratio, :page_type,
            :extraction_method, :ocr_used, :ocr_attempt, :processing_time_ms,
            :text_character_count, :status, :error_code, :error_message,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        );
        """
        cursor = c.cursor()
        for p in pages_data:
            p.setdefault("width", 0.0)
            p.setdefault("height", 0.0)
            p.setdefault("has_text", False)
            p.setdefault("text_length", 0)
            p.setdefault("text_density", 0.0)
            p.setdefault("image_count", 0)
            p.setdefault("image_area_ratio", 0.0)
            p.setdefault("page_type", "NATIVE_TEXT")
            p.setdefault("extraction_method", "NATIVE")
            p.setdefault("ocr_used", False)
            p.setdefault("ocr_attempt", 0)
            p.setdefault("processing_time_ms", 0)
            p.setdefault("text_character_count", 0)
            p.setdefault("status", PageStatus.PENDING.value)
            p.setdefault("error_code", None)
            p.setdefault("error_message", None)
        cursor.executemany(sql, pages_data)
        cursor.close()

    def get_pages_by_document_id(self, doc_id: int, conn: Optional[sqlite3.Connection] = None) -> list[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            "SELECT * FROM document_pages WHERE document_id = ? ORDER BY page_number ASC;",
            (doc_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in rows]

    def get_page(self, doc_id: int, page_number: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            "SELECT * FROM document_pages WHERE document_id = ? AND page_number = ?;",
            (doc_id, page_number),
        )
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def get_uncompleted_pages(self, doc_id: int, conn: Optional[sqlite3.Connection] = None) -> list[dict]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            "SELECT * FROM document_pages WHERE document_id = ? AND status != 'DONE' ORDER BY page_number ASC;",
            (doc_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in rows]

    def get_completed_pages_count(self, doc_id: int, conn: Optional[sqlite3.Connection] = None) -> int:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM document_pages WHERE document_id = ? AND status = 'DONE';",
            (doc_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        return row["count"] if row else 0

    def update_page_result(
        self,
        doc_id: int,
        page_number: int,
        update_data: dict,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[dict]:
        c = conn or self._get_conn()
        fields = ", ".join(f"{k} = :{k}" for k in update_data.keys())
        sql = f"UPDATE document_pages SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE document_id = :doc_id AND page_number = :page_number;"
        params = {**update_data, "doc_id": doc_id, "page_number": page_number}
        cursor = c.cursor()
        cursor.execute(sql, params)
        cursor.close()
        return self.get_page(doc_id, page_number, conn=c)
