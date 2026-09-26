import sqlite3
from typing import Optional
from app.db.database import db


class RateLimitRepository:
    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self.conn = connection

    def _get_conn(self) -> sqlite3.Connection:
        return self.conn if self.conn is not None else db.get_connection()

    def get_window_usage(
        self,
        provider: str,
        key_identifier: str,
        window_type: str,
        window_start: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> tuple[int, int]:
        """Returns (request_count, token_count) for the specified window."""
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            """
            SELECT request_count, token_count FROM rate_limit_state
            WHERE provider = ? AND key_identifier = ? AND window_type = ? AND window_start >= ?;
            """,
            (provider, key_identifier, window_type, window_start),
        )
        row = cursor.fetchone()
        cursor.close()
        if row:
            return row["request_count"], row["token_count"]
        return 0, 0

    def get_last_request_time(
        self,
        provider: str,
        key_identifier: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[str]:
        c = conn or self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            """
            SELECT MAX(last_request_at) as last_req FROM rate_limit_state
            WHERE provider = ? AND key_identifier = ?;
            """,
            (provider, key_identifier),
        )
        row = cursor.fetchone()
        cursor.close()
        return row["last_req"] if row and row["last_req"] else None

    def record_request(
        self,
        provider: str,
        key_identifier: str,
        window_type: str,
        window_start: str,
        tokens: int,
        now_iso: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        c = conn or self._get_conn()
        sql = """
        INSERT INTO rate_limit_state (
            provider, key_identifier, window_type, window_start,
            request_count, token_count, last_request_at, updated_at
        ) VALUES (
            :provider, :key_identifier, :window_type, :window_start,
            1, :tokens, :now_iso, :now_iso
        )
        ON CONFLICT(provider, key_identifier, window_type, window_start) DO UPDATE SET
            request_count = rate_limit_state.request_count + 1,
            token_count = rate_limit_state.token_count + :tokens,
            last_request_at = :now_iso,
            updated_at = :now_iso;
        """
        cursor = c.cursor()
        cursor.execute(
            sql,
            {
                "provider": provider,
                "key_identifier": key_identifier,
                "window_type": window_type,
                "window_start": window_start,
                "tokens": tokens,
                "now_iso": now_iso,
            },
        )
        cursor.close()
