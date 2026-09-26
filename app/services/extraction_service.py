import time
from pathlib import Path
from typing import Optional, Union, Callable
import fitz

from app.core.config import settings
from app.constants.statuses import PageType, PageStatus, ExtractionMethod
from app.services.pdf_service import pdf_service
from app.services.vision_provider import VisionProvider
from app.services.groq_service import groq_service
from app.db.repositories.page_repository import PageRepository
from app.db.repositories.log_repository import LogRepository
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExtractionService:
    def __init__(
        self,
        page_repo: Optional[PageRepository] = None,
        log_repo: Optional[LogRepository] = None,
        vision_provider: Optional[VisionProvider] = None,
    ):
        self.page_repo = page_repo or PageRepository()
        self.log_repo = log_repo or LogRepository()
        self.vision_provider = vision_provider or groq_service

    def initialize_document_pages(self, doc_id: int, pdf_path_or_bytes: Union[str, Path, bytes]) -> list[dict]:
        """Scan PDF and populate initial document_pages records with dimensions and classification."""
        doc = None
        pages_data = []
        try:
            if isinstance(pdf_path_or_bytes, bytes):
                doc = fitz.open(stream=pdf_path_or_bytes, filetype="pdf")
            else:
                doc = fitz.open(str(pdf_path_or_bytes))

            for page_idx in range(doc.page_count):
                page_num = page_idx + 1
                page = doc[page_idx]
                analysis = pdf_service.inspect_and_classify_page(page, page_num)

                extraction_method = (
                    ExtractionMethod.NATIVE.value
                    if analysis.page_type in (PageType.NATIVE_TEXT, PageType.EMPTY)
                    else ExtractionMethod.OCR_GROQ.value
                )

                pages_data.append(
                    {
                        "document_id": doc_id,
                        "page_number": page_num,
                        "width": analysis.width,
                        "height": analysis.height,
                        "has_text": analysis.character_count > 0,
                        "text_length": analysis.character_count,
                        "text_density": analysis.text_density,
                        "image_count": analysis.image_count,
                        "image_area_ratio": analysis.image_area_ratio,
                        "page_type": analysis.page_type.value,
                        "extraction_method": extraction_method,
                        "status": PageStatus.PENDING.value,
                    }
                )

            self.page_repo.create_batch(pages_data)
            return self.page_repo.get_pages_by_document_id(doc_id)
        finally:
            if doc:
                try:
                    doc.close()
                except Exception:
                    pass

    def extract_page(
        self,
        doc_id: int,
        job_id: int,
        page_number: int,
        fitz_doc: fitz.Document,
        custom_groq_key: Optional[str] = None,
        heartbeat_callback: Optional[Callable[[], None]] = None,
    ) -> dict:
        """Process an individual page: native text extraction or Vision OCR fallback."""
        start_time = time.time()
        page_record = self.page_repo.get_page(doc_id, page_number)
        page = fitz_doc[page_number - 1]

        if heartbeat_callback:
            heartbeat_callback()

        # Check if already completed (resumability checkpoint)
        if page_record and page_record["status"] == PageStatus.DONE.value:
            logger.info("Page %d for doc %d already DONE, skipping", page_number, doc_id)
            return page_record

        self.page_repo.update_page_result(
            doc_id, page_number, {"status": PageStatus.PROCESSING.value}
        )

        analysis = pdf_service.inspect_and_classify_page(page, page_number)
        page_type = analysis.page_type
        extracted_text = ""
        ocr_used = False
        method_used = ExtractionMethod.NATIVE.value
        error_code = None
        error_message = None

        if page_type == PageType.EMPTY:
            extracted_text = ""
            method_used = ExtractionMethod.NONE.value
            logger.info("Page %d is EMPTY", page_number)

        elif page_type in (PageType.NATIVE_TEXT, PageType.MIXED):
            extracted_text = analysis.text
            method_used = ExtractionMethod.NATIVE.value
            logger.info("Page %d extracted natively (chars=%d)", page_number, len(extracted_text))

        elif page_type == PageType.IMAGE_BASED:
            # Requires Vision OCR Fallback
            ocr_used = True
            method_used = ExtractionMethod.OCR_GROQ.value
            logger.info("Page %d is IMAGE_BASED, invoking Vision OCR", page_number)

            if self.log_repo:
                self.log_repo.create_log(
                    job_id=job_id,
                    document_id=doc_id,
                    level="INFO",
                    event="ocr_started",
                    stage="ocr_processing",
                    message=f"Starting Vision OCR for page {page_number}",
                )

            try:
                img_bytes = pdf_service.render_page_to_image(page)
                ocr_result = self.vision_provider.extract_text_from_image(
                    image_bytes=img_bytes,
                    custom_api_key=custom_groq_key,
                    job_id=job_id,
                    doc_id=doc_id,
                )
                extracted_text = ocr_result.text

                if self.log_repo:
                    self.log_repo.create_log(
                        job_id=job_id,
                        document_id=doc_id,
                        level="INFO",
                        event="ocr_completed",
                        stage="ocr_processing",
                        message=f"Completed Vision OCR for page {page_number} ({ocr_result.tokens_used} tokens)",
                    )
            except Exception as e:
                logger.error("Vision OCR failed for page %d: %s", page_number, e)
                error_code = "OCR_FAILED"
                error_message = str(e)
                # Fallback to native text if available
                extracted_text = analysis.text

        duration_ms = int((time.time() - start_time) * 1000)
        char_count = len(extracted_text.strip())

        status = PageStatus.DONE.value if not error_code else PageStatus.FAILED.value

        updated = self.page_repo.update_page_result(
            doc_id=doc_id,
            page_number=page_number,
            update_data={
                "has_text": char_count > 0,
                "text_length": char_count,
                "text_character_count": char_count,
                "text_density": char_count / (analysis.width * analysis.height) if (analysis.width * analysis.height) > 0 else 0,
                "page_type": page_type.value,
                "extraction_method": method_used,
                "ocr_used": ocr_used,
                "ocr_attempt": 1 if ocr_used else 0,
                "processing_time_ms": duration_ms,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
            },
        )

        return {
            **updated,
            "text": extracted_text,
        }


extraction_service = ExtractionService()
