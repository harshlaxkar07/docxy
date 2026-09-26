import pytest
from app.services.pdf_service import pdf_service
from app.core.exceptions import (
    PDFValidationError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFPageLimitError,
)
from app.core.config import settings


def test_validate_valid_pdf(sample_native_pdf_bytes):
    info = pdf_service.validate_pdf(sample_native_pdf_bytes)
    assert info["page_count"] == 3
    assert info["is_encrypted"] is False


def test_validate_corrupted_pdf():
    corrupt_bytes = b"Not a real PDF file contents here"
    with pytest.raises(PDFCorruptedError):
        pdf_service.validate_pdf(corrupt_bytes)


def test_validate_page_limit(monkeypatch, sample_native_pdf_bytes):
    monkeypatch.setattr(settings, "MAX_PAGES_PER_DOCUMENT", 2)
    with pytest.raises(PDFPageLimitError):
        pdf_service.validate_pdf(sample_native_pdf_bytes)
