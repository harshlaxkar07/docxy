import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import fitz


from app.core.config import settings
from app.constants.statuses import JobStatus, JobStage, DocumentStatus
from app.core.logging import get_logger
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.page_repository import PageRepository
from app.db.repositories.result_repository import ResultRepository
from app.db.repositories.log_repository import LogRepository
from app.services.pdf_service import pdf_service
from app.services.extraction_service import extraction_service
from app.services.txt_service import txt_service
from app.services.s3_service import s3_service
from app.services.temp_manager import temp_manager

logger = get_logger(__name__)


class TaskProcessor:
    def __init__(
        self,
        doc_repo: Optional[DocumentRepository] = None,
        job_repo: Optional[JobRepository] = None,
        page_repo: Optional[PageRepository] = None,
        result_repo: Optional[ResultRepository] = None,
        log_repo: Optional[LogRepository] = None,
    ):
        self.doc_repo = doc_repo or DocumentRepository()
        self.job_repo = job_repo or JobRepository()
        self.page_repo = page_repo or PageRepository()
        self.result_repo = result_repo or ResultRepository()
        self.log_repo = log_repo or LogRepository()

    def process_job(self, job: dict, custom_groq_key: Optional[str] = None) -> None:
        job_id = job["id"]
        job_uuid = job["job_uuid"]
        doc_id = job["document_id"]

        logger.info("Processing job %s (doc_id=%d)", job_uuid, doc_id)
        start_time = time.time()

        document = self.doc_repo.get_by_id(doc_id)
        if not document:
            logger.error("Document %d not found for job %s", doc_id, job_uuid)
            self.job_repo.update_status(
                job_id,
                JobStatus.FAILED,
                error_code="DOCUMENT_NOT_FOUND",
                error_message=f"Document {doc_id} not found",
            )
            return

        doc_uuid = document["uuid"]

        # Ensure status is at least RUNNING
        curr_job = self.job_repo.get_by_id(job_id)
        if curr_job and curr_job["status"] == JobStatus.QUEUED.value:
            self.job_repo.update_status(job_id, JobStatus.RUNNING, stage=JobStage.VALIDATION)

        # Log job start
        self.log_repo.create_log(
            job_id=job_id,
            document_id=doc_id,
            level="INFO",
            event="job_started",
            stage=JobStage.PAGE_INSPECTION.value,
            message=f"Worker started processing job {job_uuid}",
        )


        with temp_manager.job_temp_context(job_uuid) as job_temp_dir:
            try:
                # 1. Obtain local copy of original PDF
                local_pdf_path = job_temp_dir / f"{document['stored_filename']}"
                if document.get("s3_key"):
                    s3_service.download_file(document["s3_key"], local_pdf_path)
                else:
                    # Look in local storage or temp
                    fallback_path = Path(settings.LOCAL_STORAGE_DIR) / document["stored_filename"]
                    if fallback_path.exists():
                        import shutil
                        shutil.copy2(fallback_path, local_pdf_path)
                    else:
                        raise FileNotFoundError(f"Original file not found for document {doc_uuid}")

                # 2. Inspect & validate PDF
                self.job_repo.update_status(job_id, JobStatus.PROCESSING, stage=JobStage.PAGE_INSPECTION)
                validation_info = pdf_service.validate_pdf(local_pdf_path)
                total_pages = validation_info["page_count"]

                # Update document page count if not already set
                self.doc_repo.update(doc_id, {"page_count": total_pages})

                # 3. Ensure S3 Upload for Original PDF if not already done
                if not document.get("s3_key") and settings.AWS_ENABLED:
                    self.job_repo.update_status(job_id, JobStatus.PROCESSING, stage=JobStage.S3_UPLOAD_ORIGINAL)
                    s3_key = s3_service.generate_canonical_key("documents", doc_uuid, "original.pdf")
                    upload_res = s3_service.upload_file(local_pdf_path, s3_key, content_type="application/pdf")
                    self.doc_repo.update(
                        doc_id,
                        {
                            "storage_provider": upload_res["storage_provider"],
                            "s3_bucket": upload_res["s3_bucket"],
                            "s3_key": upload_res["s3_key"],
                            "s3_url": upload_res["s3_url"],
                        },
                    )
                    self.result_repo.save_output_file(
                        document_id=doc_id,
                        job_id=job_id,
                        file_type="ORIGINAL_PDF",
                        filename=document["original_filename"],
                        mime_type="application/pdf",
                        file_size_bytes=upload_res["file_size_bytes"],
                        s3_bucket=upload_res["s3_bucket"],
                        s3_key=upload_res["s3_key"],
                        s3_url=upload_res["s3_url"],
                    )

                # 4. Initialize pages table if not present
                existing_pages = self.page_repo.get_pages_by_document_id(doc_id)
                if not existing_pages:
                    extraction_service.initialize_document_pages(doc_id, local_pdf_path)

                # 5. Process page-by-page
                self.job_repo.update_status(job_id, JobStatus.PROCESSING, stage=JobStage.NATIVE_EXTRACTION)

                fitz_doc = fitz.open(str(local_pdf_path))
                extracted_pages_data = []
                ocr_pages_count = 0

                try:
                    for page_num in range(1, total_pages + 1):
                        def _heartbeat():
                            self.job_repo.update_heartbeat(job_id)

                        page_res = extraction_service.extract_page(
                            doc_id=doc_id,
                            job_id=job_id,
                            page_number=page_num,
                            fitz_doc=fitz_doc,
                            custom_groq_key=custom_groq_key,
                            heartbeat_callback=_heartbeat,
                        )
                        if page_res.get("ocr_used"):
                            ocr_pages_count += 1

                        extracted_pages_data.append(page_res)
                        self.job_repo.update_progress(job_id, processed_pages=page_num, total_pages=total_pages)

                finally:
                    fitz_doc.close()

                # 6. Aggregate extracted text and format TXT
                self.job_repo.update_status(job_id, JobStatus.PROCESSING, stage=JobStage.TEXT_AGGREGATION)
                full_text, char_count, word_count, text_hash = txt_service.format_document_text(
                    pages=extracted_pages_data,
                    document_metadata=self.doc_repo.get_by_id(doc_id),
                )

                # Save extracted text record
                self.result_repo.save_extracted_text(
                    document_id=doc_id,
                    job_id=job_id,
                    text=full_text,
                    character_count=char_count,
                    word_count=word_count,
                    text_hash=text_hash,
                )

                # 7. Generate TXT output file and upload to storage
                self.job_repo.update_status(job_id, JobStatus.PROCESSING, stage=JobStage.TXT_GENERATION)
                txt_filename = f"{Path(document['original_filename']).stem}_extracted.txt"
                local_txt_path = job_temp_dir / txt_filename
                local_txt_path.write_text(full_text, encoding="utf-8")

                self.job_repo.update_status(job_id, JobStatus.PROCESSING, stage=JobStage.S3_UPLOAD_TXT)
                txt_s3_key = s3_service.generate_canonical_key("extracted", doc_uuid, "extracted.txt")
                txt_upload_res = s3_service.upload_file(local_txt_path, txt_s3_key, content_type="text/plain; charset=utf-8")

                self.result_repo.save_output_file(
                    document_id=doc_id,
                    job_id=job_id,
                    file_type="EXTRACTED_TXT",
                    filename=txt_filename,
                    mime_type="text/plain",
                    file_size_bytes=txt_upload_res["file_size_bytes"],
                    s3_bucket=txt_upload_res["s3_bucket"],
                    s3_key=txt_upload_res["s3_key"],
                    s3_url=txt_upload_res["s3_url"],
                )

                # 8. Mark document and job complete
                total_duration_ms = int((time.time() - start_time) * 1000)
                extraction_method = "HYBRID_OCR" if ocr_pages_count > 0 else "NATIVE"

                self.doc_repo.update(
                    doc_id,
                    {
                        "status": DocumentStatus.COMPLETED.value,
                        "processing_completed_at": datetime.now(timezone.utc).isoformat(),
                        "processing_duration_ms": total_duration_ms,
                        "extraction_method": extraction_method,
                        "text_character_count": char_count,
                        "word_count": word_count,
                    },
                )

                self.job_repo.update_status(
                    job_id=job_id,
                    status=JobStatus.DONE,
                    stage=JobStage.COMPLETED,
                    duration_ms=total_duration_ms,
                )

                self.log_repo.create_log(
                    job_id=job_id,
                    document_id=doc_id,
                    level="INFO",
                    event="job_completed",
                    stage=JobStage.COMPLETED.value,
                    message=f"Job {job_uuid} completed successfully in {total_duration_ms}ms ({total_pages} pages, {ocr_pages_count} OCR)",
                )

                logger.info(
                    "Job %s completed successfully in %dms (pages=%d, OCR=%d)",
                    job_uuid,
                    total_duration_ms,
                    total_pages,
                    ocr_pages_count,
                )

            except Exception as e:
                total_duration_ms = int((time.time() - start_time) * 1000)
                logger.error("Job %s failed with exception: %s", job_uuid, e, exc_info=True)

                self.doc_repo.update(
                    doc_id,
                    {
                        "status": DocumentStatus.FAILED.value,
                        "processing_duration_ms": total_duration_ms,
                    },
                )

                self.job_repo.update_status(
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    stage=JobStage.FAILED,
                    error_code="PROCESSING_ERROR",
                    error_message=str(e),
                    duration_ms=total_duration_ms,
                )

                self.log_repo.create_log(
                    job_id=job_id,
                    document_id=doc_id,
                    level="ERROR",
                    event="job_failed",
                    stage=JobStage.FAILED.value,
                    message=f"Job {job_uuid} failed: {e}",
                )


task_processor = TaskProcessor()
