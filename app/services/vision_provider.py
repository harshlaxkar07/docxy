from abc import ABC, abstractmethod
from typing import Optional


class OCRResult:
    def __init__(
        self,
        text: str,
        confidence: float = 1.0,
        tokens_used: int = 0,
        response_time_ms: int = 0,
        provider: str = "",
        model: str = "",
    ):
        self.text = text
        self.confidence = confidence
        self.tokens_used = tokens_used
        self.response_time_ms = response_time_ms
        self.provider = provider
        self.model = model


class VisionProvider(ABC):
    @abstractmethod
    def extract_text_from_image(
        self,
        image_bytes: bytes,
        custom_api_key: Optional[str] = None,
        job_id: Optional[int] = None,
        doc_id: Optional[int] = None,
    ) -> OCRResult:
        """Extract text from rendered page image."""
        pass
