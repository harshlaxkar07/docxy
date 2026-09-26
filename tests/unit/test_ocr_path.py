"""Coverage for the Vision OCR fallback.

The suite forces GROQ_ENABLED=false, so before this file the entire OCR branch
— provider dispatch, usage recording, retry and the native-text fallback on
failure — was unverified. A fake VisionProvider exercises it without a network
call or an API key.
"""

import fitz
import pytest

from app.constants.statuses import ExtractionMethod, PageStatus, PageType
from app.db.repositories.page_repository import PageRepository
from app.services.document_service import document_service
from app.services.extraction_service import ExtractionService
from app.services.vision_provider import OCRResult, VisionProvider


class FakeVisionProvider(VisionProvider):
    """Records its calls and returns canned OCR text."""

    def __init__(self, text: str = "TEXT RECOVERED BY OCR", fail_with: Exception | None = None):
        self.text = text
        self.fail_with = fail_with
        self.calls: list[dict] = []

    def extract_text_from_image(
        self,
        image_bytes: bytes,
        custom_api_key=None,
        job_id=None,
        doc_id=None,
        **kwargs,
    ) -> OCRResult:
        self.calls.append(
            {
                "image_bytes_len": len(image_bytes),
                "custom_api_key": custom_api_key,
                "job_id": job_id,
                "doc_id": doc_id,
            }
        )
        if self.fail_with:
            raise self.fail_with
        return OCRResult(text=self.text, tokens_used=42, model="fake-vision", response_time_ms=5)


@pytest.fixture
def image_document(sample_image_pdf_bytes):
    """An uploaded image-only document with its pages initialised."""
    upload = document_service.process_upload(
        file_bytes=sample_image_pdf_bytes,
        original_filename="scanned.pdf",
    )
    from app.db.repositories.job_repository import JobRepository

    job = JobRepository().get_by_uuid(upload["job_id"])
    return job, sample_image_pdf_bytes


def test_image_page_is_routed_to_the_vision_provider(image_document):
    job, pdf_bytes = image_document
    doc_id = job["document_id"]

    provider = FakeVisionProvider()
    service = ExtractionService(vision_provider=provider)
    service.initialize_document_pages(doc_id, pdf_bytes)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        result = service.extract_page(doc_id, job["id"], 1, doc)
    finally:
        doc.close()

    assert len(provider.calls) == 1, "the vision provider was not called for an image page"
    assert provider.calls[0]["image_bytes_len"] > 0, "no rendered image was passed"
    assert result["text"] == "TEXT RECOVERED BY OCR"
    assert result["ocr_used"], "page was not marked as OCR-processed"
    assert result["extraction_method"] == ExtractionMethod.OCR_GROQ.value
    assert result["status"] == PageStatus.DONE.value

    stored = PageRepository().get_page(doc_id, 1)
    assert stored["page_type"] == PageType.IMAGE_BASED.value
    assert stored["ocr_used"] == 1
    assert stored["text"] == "TEXT RECOVERED BY OCR", "OCR text was not persisted"


def test_custom_api_key_reaches_the_provider(image_document):
    job, pdf_bytes = image_document
    doc_id = job["document_id"]

    provider = FakeVisionProvider()
    service = ExtractionService(vision_provider=provider)
    service.initialize_document_pages(doc_id, pdf_bytes)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        service.extract_page(doc_id, job["id"], 1, doc, custom_groq_key="per-request-key")
    finally:
        doc.close()

    assert provider.calls[0]["custom_api_key"] == "per-request-key"


def test_ocr_failure_falls_back_instead_of_losing_the_page(image_document):
    """A failed OCR call must not abort the job — the page is marked FAILED and
    keeps whatever native text existed."""
    job, pdf_bytes = image_document
    doc_id = job["document_id"]

    provider = FakeVisionProvider(fail_with=RuntimeError("vision provider exploded"))
    service = ExtractionService(vision_provider=provider)
    service.initialize_document_pages(doc_id, pdf_bytes)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        result = service.extract_page(doc_id, job["id"], 1, doc)
    finally:
        doc.close()

    assert result["status"] == PageStatus.FAILED.value
    assert result["error_code"] == "OCR_FAILED"
    assert "vision provider exploded" in result["error_message"]
    # The page record survives so the rest of the document still completes.
    assert PageRepository().get_page(doc_id, 1) is not None


def test_native_page_never_calls_the_vision_provider(sample_native_pdf_bytes):
    """The whole point of the pipeline: typed pages cost nothing."""
    upload = document_service.process_upload(
        file_bytes=sample_native_pdf_bytes,
        original_filename="native_only.pdf",
    )
    from app.db.repositories.job_repository import JobRepository

    job = JobRepository().get_by_uuid(upload["job_id"])
    doc_id = job["document_id"]

    provider = FakeVisionProvider()
    service = ExtractionService(vision_provider=provider)
    service.initialize_document_pages(doc_id, sample_native_pdf_bytes)

    doc = fitz.open(stream=sample_native_pdf_bytes, filetype="pdf")
    try:
        for page_no in (1, 2, 3):
            result = service.extract_page(doc_id, job["id"], page_no, doc)
            assert not result["ocr_used"]
    finally:
        doc.close()

    assert provider.calls == [], "a native page was sent to the vision model"
