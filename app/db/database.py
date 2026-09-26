import sqlite3
import contextlib
from pathlib import Path
from typing import Generator, Optional
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Database:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path

    @property
    def db_path(self) -> str:
        return self._db_path or settings.DATABASE_PATH

    def _ensure_db_dir(self) -> None:
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Create and configure a new SQLite connection."""
        self._ensure_db_dir()
        conn = sqlite3.connect(
            self.db_path,
            timeout=10.0,
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode by default; manual transactions via context manager
        )
        conn.row_factory = sqlite3.Row
        
        # Configure PRAGMAs for performance, concurrency, and integrity
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()
        
        return conn

    @contextlib.contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding a managed connection."""
        conn = self.get_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing an atomic transaction (BEGIN / COMMIT / ROLLBACK)."""
        conn = self.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.execute("COMMIT;")
        except Exception as e:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise e
        finally:
            conn.close()


db = Database()
