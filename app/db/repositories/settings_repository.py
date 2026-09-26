import sqlite3
from typing import Any, Optional

from app.db.database import db

# Only these keys may be overridden at runtime. An allowlist keeps a settings
# write from redefining paths, credentials or anything else security-relevant.
MUTABLE_KEYS: dict[str, str] = {
    "PDF_MIN_TEXT_LENGTH": "int",
    "PDF_MIN_TEXT_DENSITY": "float",
    "PDF_MIN_IMAGE_AREA_RATIO": "float",
    "TXT_INCLUDE_PAGE_MARKERS": "bool",
    "TXT_INCLUDE_METADATA": "bool",
    "GROQ_ENABLED": "bool",
    "GROQ_MODEL": "string",
    "WORKER_POLL_INTERVAL_SECONDS": "float",
    "JOB_STALE_TIMEOUT_SECONDS": "float",
}

SECRET_KEYS = {"GROQ_API_KEY"}


def _coerce(value: Optional[str], value_type: str) -> Any:
    if value is None:
        return None
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return value


class SettingsRepository:
    """Runtime setting overrides, persisted in the `settings` table.

    Values here take precedence over the environment for the keys in
    MUTABLE_KEYS, so thresholds can be tuned without a restart.
    """

    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        self.conn = connection

    def _get_conn(self) -> sqlite3.Connection:
        return self.conn if self.conn is not None else db.get_connection()

    def get_all(self, include_secrets: bool = False) -> dict[str, Any]:
        c = self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT key, value, value_type, is_secret FROM settings;")
        rows = cursor.fetchall()
        cursor.close()

        out: dict[str, Any] = {}
        for row in rows:
            if row["is_secret"] and not include_secrets:
                continue
            out[row["key"]] = _coerce(row["value"], row["value_type"])
        return out

    def get(self, key: str) -> Any:
        c = self._get_conn()
        cursor = c.cursor()
        cursor.execute("SELECT value, value_type FROM settings WHERE key = ?;", (key,))
        row = cursor.fetchone()
        cursor.close()
        return _coerce(row["value"], row["value_type"]) if row else None

    def set(self, key: str, value: Any, value_type: Optional[str] = None) -> dict:
        resolved_type = value_type or MUTABLE_KEYS.get(key, "string")
        c = self._get_conn()
        cursor = c.cursor()
        cursor.execute(
            """
            INSERT INTO settings (key, value, value_type, is_secret, updated_at)
            VALUES (:key, :value, :value_type, :is_secret, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                value_type = excluded.value_type,
                is_secret = excluded.is_secret,
                updated_at = CURRENT_TIMESTAMP;
            """,
            {
                "key": key,
                "value": None if value is None else str(value),
                "value_type": resolved_type,
                "is_secret": 1 if key in SECRET_KEYS else 0,
            },
        )
        cursor.close()
        return {"key": key, "value": self.get(key), "value_type": resolved_type}

    def delete(self, key: str) -> bool:
        c = self._get_conn()
        cursor = c.cursor()
        cursor.execute("DELETE FROM settings WHERE key = ?;", (key,))
        deleted = cursor.rowcount > 0
        cursor.close()
        return deleted


settings_repository = SettingsRepository()
