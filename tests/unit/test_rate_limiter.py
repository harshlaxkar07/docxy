import pytest
import time
from app.services.rate_limiter import GroqRateLimiter
from app.db.repositories.rate_limit_repository import RateLimitRepository
from app.core.exceptions import GroqRateLimitError
from app.core.config import settings


def test_rate_limiter_acquire_and_increment():
    limiter = GroqRateLimiter(RateLimitRepository())
    provider = "test_groq"
    key_id = "test_key_1"

    # First acquire should succeed immediately
    limiter.acquire(provider=provider, key_identifier=key_id, auto_sleep=False)

    usage, _ = limiter.repo.get_window_usage(provider, key_id, "day", "2000-01-01 00:00:00")
    assert usage >= 1


def test_rate_limiter_min_gap_enforced(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_MIN_REQUEST_GAP_SECONDS", 1.0)
    limiter = GroqRateLimiter(RateLimitRepository())
    provider = "test_gap_provider"
    key_id = "test_key_gap"

    # Acquire once
    limiter.acquire(provider=provider, key_identifier=key_id, auto_sleep=False)

    # Immediate second acquire should raise GroqRateLimitError if auto_sleep=False
    with pytest.raises(GroqRateLimitError):
        limiter.acquire(provider=provider, key_identifier=key_id, auto_sleep=False)
