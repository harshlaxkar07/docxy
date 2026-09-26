"""Effective settings = environment defaults, overridden by the `settings` table.

`app/core/config.py` is read once at import. This layer lets a small allowlist
of keys be retuned at runtime without a restart. Lookups are cached briefly so
a per-page read does not hit SQLite on every call.
"""

import threading
import time
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.repositories.settings_repository import (
    MUTABLE_KEYS,
    SECRET_KEYS,
    settings_repository,
)

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 5.0

_lock = threading.Lock()
_cache: dict[str, Any] = {}
_cache_expires_at = 0.0


def invalidate() -> None:
    """Drop the cache so the next read reflects a just-written override."""
    global _cache_expires_at
    with _lock:
        _cache.clear()
        _cache_expires_at = 0.0


def _overrides() -> dict[str, Any]:
    global _cache, _cache_expires_at
    now = time.monotonic()
    with _lock:
        if now < _cache_expires_at:
            return _cache
    try:
        fresh = settings_repository.get_all(include_secrets=True)
    except Exception as e:
        # A settings-table problem must never stop extraction.
        logger.warning("Could not read runtime settings, using environment: %s", e)
        fresh = {}
    with _lock:
        _cache = fresh
        _cache_expires_at = now + CACHE_TTL_SECONDS
        return _cache


def get(key: str) -> Any:
    """Effective value for a key: runtime override if set, else the env value."""
    value = _overrides().get(key)
    if value is not None:
        return value
    return getattr(settings, key, None)


def effective_settings() -> dict[str, Any]:
    """Every tunable key with its effective value, secrets excluded."""
    return {key: get(key) for key in MUTABLE_KEYS if key not in SECRET_KEYS}
