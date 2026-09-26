import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from app.core.config import settings
from app.db.repositories.rate_limit_repository import RateLimitRepository
from app.core.exceptions import GroqRateLimitError
from app.core.logging import get_logger

logger = get_logger(__name__)


class GroqRateLimiter:
    def __init__(self, repository: Optional[RateLimitRepository] = None):
        self.repo = repository or RateLimitRepository()

    def _get_window_keys(self, now: datetime) -> list[tuple[str, str, int]]:
        """Return list of (window_type, window_start_iso, max_limit)."""
        sec_start = now.strftime("%Y-%m-%d %H:%M:%S")
        min_start = now.strftime("%Y-%m-%d %H:%M:00")
        hour_start = now.strftime("%Y-%m-%d %H:00:00")
        day_start = now.strftime("%Y-%m-%d 00:00:00")

        return [
            ("second", sec_start, settings.GROQ_REQUESTS_PER_SECOND),
            ("minute", min_start, settings.GROQ_REQUESTS_PER_MINUTE),
            ("hour", hour_start, settings.GROQ_REQUESTS_PER_HOUR),
            ("day", day_start, settings.GROQ_REQUESTS_PER_DAY),
        ]

    def acquire(self, provider: str = "groq", key_identifier: str = "default", auto_sleep: bool = True) -> None:
        """
        Check rate limit windows and pacing gap. If auto_sleep=True, sleeps until
        limit clears; otherwise raises GroqRateLimitError.
        """
        max_wait_attempts = 10
        attempts = 0

        while attempts < max_wait_attempts:
            attempts += 1
            now = datetime.now(timezone.utc)
            now_iso = now.strftime("%Y-%m-%d %H:%M:%S")


            # 1. Check Minimum Request Gap
            last_req_str = self.repo.get_last_request_time(provider, key_identifier)
            if last_req_str:
                try:
                    last_req = datetime.fromisoformat(last_req_str)
                    elapsed = (now - last_req).total_seconds()
                    gap_required = settings.GROQ_MIN_REQUEST_GAP_SECONDS
                    if elapsed < gap_required:
                        wait_seconds = gap_required - elapsed
                        if auto_sleep:
                            logger.debug("Pacing gap: sleeping %.2fs", wait_seconds)
                            time.sleep(wait_seconds)
                            continue
                        else:
                            raise GroqRateLimitError(
                                f"Minimum request gap not met. Wait {wait_seconds:.1f}s",
                                retry_after=int(wait_seconds) + 1,
                            )
                except Exception as e:
                    if isinstance(e, GroqRateLimitError):
                        raise
                    logger.warning("Failed to parse last_request_at '%s': %s", last_req_str, e)

            # 2. Check Sliding Windows
            windows = self._get_window_keys(now)
            blocked_window = None
            max_delay = 0.0

            for w_type, w_start, max_limit in windows:
                if max_limit is None or max_limit <= 0:
                    continue
                req_count, _ = self.repo.get_window_usage(provider, key_identifier, w_type, w_start)
                if req_count >= max_limit:
                    blocked_window = w_type
                    if w_type == "second":
                        max_delay = max(max_delay, 1.0)
                    elif w_type == "minute":
                        # Seconds until next minute
                        next_min = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
                        max_delay = max(max_delay, (next_min - now).total_seconds() + 0.1)
                    elif w_type == "hour":
                        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                        max_delay = max(max_delay, (next_hour - now).total_seconds() + 0.1)
                    elif w_type == "day":
                        next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                        max_delay = max(max_delay, (next_day - now).total_seconds() + 0.1)

            if blocked_window:
                logger.warning(
                    "Rate limit reached for provider '%s' on window '%s'. Need wait: %.1fs",
                    provider,
                    blocked_window,
                    max_delay,
                )
                if auto_sleep and max_delay <= 60.0:
                    time.sleep(max_delay)
                    continue
                else:
                    raise GroqRateLimitError(
                        f"Rate limit exceeded on window '{blocked_window}' for provider '{provider}'",
                        retry_after=int(max_delay) + 1,
                    )

            # Granted: Record in all windows
            for w_type, w_start, _ in windows:
                self.repo.record_request(provider, key_identifier, w_type, w_start, tokens=0, now_iso=now_iso)
            return

        raise GroqRateLimitError("Rate limit wait timeout exceeded", retry_after=60)


rate_limiter = GroqRateLimiter()
