import base64
import time
from datetime import datetime
from typing import Optional
from groq import Groq, APIError, RateLimitError, APITimeoutError, AuthenticationError

from app.core.config import settings
from app.services.vision_provider import VisionProvider, OCRResult
from app.services.rate_limiter import rate_limiter
from app.db.repositories.usage_repository import UsageRepository
from app.core.exceptions import (
    GroqAPIError,
    GroqRateLimitError,
    GroqTimeoutError,
    ConfigurationError,
)
from app.utils.retry import retry_with_backoff
from app.core.logging import get_logger

logger = get_logger(__name__)

OCR_PROMPT = (
    "Extract all readable text from this document image exactly as presented. "
    "Preserve original layout, paragraphs, tables, lists, and formatting as closely as possible. "
    "Do not add conversational preamble, commentary, or markdown code fences. "
    "Output ONLY the extracted document text."
)


class GroqVisionProvider(VisionProvider):
    def __init__(self, usage_repo: Optional[UsageRepository] = None):
        self.usage_repo = usage_repo or UsageRepository()
        self.enabled = settings.GROQ_ENABLED
        self.default_api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        self.timeout = settings.GROQ_TIMEOUT_SECONDS

    def _get_client(self, api_key: Optional[str] = None) -> Groq:
        key = api_key or self.default_api_key
        if not key:
            raise ConfigurationError("Groq API key is not configured")
        return Groq(api_key=key, timeout=self.timeout)

    def extract_text_from_image(
        self,
        image_bytes: bytes,
        custom_api_key: Optional[str] = None,
        job_id: Optional[int] = None,
        doc_id: Optional[int] = None,
    ) -> OCRResult:
        if not self.enabled and not custom_api_key:
            raise ConfigurationError("Groq Vision OCR is disabled or not configured")

        api_key = custom_api_key or self.default_api_key
        if not api_key:
            raise ConfigurationError("No Groq API key available for extraction")

        key_id = f"key_{hash(api_key) & 0xFFFFFFFF:08x}"

        def _execute_groq_call() -> OCRResult:
            # 1. Acquire rate limit slot
            rate_limiter.acquire(provider="groq", key_identifier=key_id, auto_sleep=True)

            # 2. Prepare payload
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            image_url = f"data:image/jpeg;base64,{b64_image}"

            client = self._get_client(api_key)
            start_time = time.time()
            start_iso = datetime.utcnow().isoformat()

            try:
                chat_completion = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": OCR_PROMPT},
                                {"type": "image_url", "image_url": {"url": image_url}},
                            ],
                        }
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                end_iso = datetime.utcnow().isoformat()

                text = chat_completion.choices[0].message.content or ""
                tokens = 0
                if chat_completion.usage:
                    tokens = chat_completion.usage.total_tokens

                # Record successful usage
                self.usage_repo.record_usage(
                    provider="groq",
                    model=self.model,
                    job_id=job_id,
                    document_id=doc_id,
                    request_type="OCR_VISION",
                    status="SUCCESS",
                    request_started_at=start_iso,
                    request_completed_at=end_iso,
                    response_time_ms=duration_ms,
                    tokens_used=tokens,
                )

                logger.info(
                    "Groq OCR completed in %dms (chars=%d, tokens=%d)",
                    duration_ms,
                    len(text),
                    tokens,
                )
                return OCRResult(
                    text=text,
                    tokens_used=tokens,
                    response_time_ms=duration_ms,
                    provider="groq",
                    model=self.model,
                )

            except RateLimitError as e:
                duration_ms = int((time.time() - start_time) * 1000)
                end_iso = datetime.utcnow().isoformat()
                self.usage_repo.record_usage(
                    provider="groq",
                    model=self.model,
                    job_id=job_id,
                    document_id=doc_id,
                    request_type="OCR_VISION",
                    status="RATE_LIMITED",
                    request_started_at=start_iso,
                    request_completed_at=end_iso,
                    response_time_ms=duration_ms,
                    error_code="RATE_LIMIT",
                )
                logger.warning("Groq API rate limit error: %s", e)
                raise GroqRateLimitError(f"Groq API rate limit: {e}")

            except APITimeoutError as e:
                duration_ms = int((time.time() - start_time) * 1000)
                end_iso = datetime.utcnow().isoformat()
                self.usage_repo.record_usage(
                    provider="groq",
                    model=self.model,
                    job_id=job_id,
                    document_id=doc_id,
                    request_type="OCR_VISION",
                    status="TIMEOUT",
                    request_started_at=start_iso,
                    request_completed_at=end_iso,
                    response_time_ms=duration_ms,
                    error_code="TIMEOUT",
                )
                logger.error("Groq API timeout: %s", e)
                raise GroqTimeoutError(f"Groq API timeout: {e}")

            except AuthenticationError as e:
                logger.error("Groq API authentication error: %s", e)
                raise GroqAPIError(f"Groq API auth failure: {e}", status_code=401)

            except APIError as e:
                duration_ms = int((time.time() - start_time) * 1000)
                end_iso = datetime.utcnow().isoformat()
                self.usage_repo.record_usage(
                    provider="groq",
                    model=self.model,
                    job_id=job_id,
                    document_id=doc_id,
                    request_type="OCR_VISION",
                    status="ERROR",
                    request_started_at=start_iso,
                    request_completed_at=end_iso,
                    response_time_ms=duration_ms,
                    error_code="API_ERROR",
                )
                logger.error("Groq API error: %s", e)
                raise GroqAPIError(f"Groq API error: {e}")

        return retry_with_backoff(
            _execute_groq_call,
            max_retries=settings.GROQ_MAX_RETRIES,
            base_delay=2.0,
            retryable_exceptions=(GroqRateLimitError, GroqTimeoutError),
        )


groq_service = GroqVisionProvider()
