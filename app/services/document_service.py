import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, BinaryIO

from app.core.config import settings
from app.constants.statuses import DocumentStatus, JobStatus, JobStage
from app.core.exceptions import (
    PDFValidationError,
    PDFTooLargeError,
    DocumentNotFoundError,
)
from app.utils.file_utils import sanitize_filename, get_file_extension, is_pdf_header, generate_uuid
from app.utils.hashing import compute_sha256
from app.db.database import db
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.result_repository import ResultRepository
from app.db.repositories.page_repository import PageRepository
from app.services.pdf_service import pdf_service
from app.services.s3_service import s3_service
from app.core.logging import get_logger

logger = get_logger(__name__)


class DocumentService:
    def __init__(
        self,
        doc_repo: Optional[DocumentRepository] = None,
        job_repo: Optional[JobRepository] = None,
        result_repo: Optional[ResultRepository] = None,
        page_repo: Optional[PageRepository] = None,
    ):
        self.doc_repo = doc_repo or DocumentRepository()
        self.job_repo = job_repo or JobRepository()
        self.result_repo = result_repo or ResultRepository()
        self.page_repo = page_repo or PageRepository()

    def process_upload(
        self,
        file_bytes: Optional[bytes] = None,
        original_filename: str = "",
        content_type: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        file_path: Optional[Path] = None,
    ) -> dict:
        """Validate, deduplicate, persist, and queue a new PDF document.

        Accepts either the raw bytes or a path to an already-staged file. The
        HTTP route streams to a temp file and passes `file_path`, so a large
        upload is never held in memory; `file_bytes` remains for direct calls.
        """
        if file_path is None and file_bytes is None:
            raise PDFValidationError("No file content supplied")

        # `source` is what the hasher and PyMuPDF read — a path or the bytes.
        source: Union[Path, bytes] = file_path if file_path is not None else file_bytes

        # 1. Size Validation
        file_size = file_path.stat().st_size if file_path is not None else len(file_bytes)
        if file_size == 0:
            raise PDFValidationError("Uploaded file is empty")
        if file_size > settings.max_upload_size_bytes:
            raise PDFTooLargeError(
                f"File size ({file_size / (1024*1024):.1f} MB) exceeds limit of {settings.MAX_UPLOAD_SIZE_MB} MB"
            )

        # 2. Header & Filename Validation
        clean_filename = sanitize_filename(original_filename)
        ext = get_file_extension(clean_filename)
        if ext != "pdf":
            raise PDFValidationError(f"Invalid file extension '.{ext}'. Only PDF files are supported.")

        if file_path is not None:
            with open(file_path, "rb") as fh:
                header = fh.read(10)
        else:
            header = file_bytes[:10]
        if not is_pdf_header(header):
            raise PDFValidationError("File does not start with valid PDF binary signature (%PDF-)")

        # 3. PDF Structural Validation (PyMuPDF)
        pdf_info = pdf_service.validate_pdf(source)
        page_count = pdf_info["page_count"]

        # 4. Hash Calculation & Duplicate Detection
        file_hash = compute_sha256(source)
        existing_doc = self.doc_repo.get_by_hash(file_hash)
        if existing_doc and existing_doc["status"] == DocumentStatus.COMPLETED.value:
            existing_job = self.job_repo.get_by_document_id(existing_doc["id"])
            if existing_job:
                logger.info(
                    "Duplicate document detected (hash=%s). Reusing doc %s, job %s",
                    file_hash,
                    existing_doc["uuid"],
                    existing_job["job_uuid"],
                )
                return {
                    "document_id": existing_doc["uuid"],
                    "job_id": existing_job["job_uuid"],
                    "status": existing_job["status"].lower(),
                    "is_duplicate": True,
                    "message": "Duplicate document detected. Returning existing completed job.",
                }

        # 5. Idempotency Check
        if idempotency_key:
            existing_idempotent_job = self.job_repo.get_by_idempotency_key(idempotency_key)
            if existing_idempotent_job:
                doc = self.doc_repo.get_by_id(existing_idempotent_job["document_id"])
                logger.info(
                    "Idempotent submission match for key '%s'. Returning job %s",
                    idempotency_key,
                    existing_idempotent_job["job_uuid"],
                )
                return {
                    "document_id": doc["uuid"] if doc else "",
                    "job_id": existing_idempotent_job["job_uuid"],
                    "status": existing_idempotent_job["status"].lower(),
                    "is_duplicate": False,
                    "message": "Idempotent request matched existing job.",
                }

        # 6. Generate UUIDs and Store File
        doc_uuid = generate_uuid()
        job_uuid = generate_uuid()
        stored_filename = f"{doc_uuid}_{clean_filename}"

        # Save copy to local storage or S3
        storage_dir = Path(settings.LOCAL_STORAGE_DIR)
        storage_dir.mkdir(parents=True, exist_ok=True)
        local_stored_path = storage_dir / stored_filename
        if file_path is not None:
            shutil.copyfile(file_path, local_stored_path)
        else:
            local_stored_path.write_bytes(file_bytes)

        s3_bucket = None
        s3_key = None
        s3_url = None
        storage_provider = "LOCAL"

        if settings.AWS_ENABLED:
            try:
                s3_key = s3_service.generate_canonical_key("documents", doc_uuid, "original.pdf")
                upload_res = s3_service.upload_file(source, s3_key, content_type="application/pdf")
                storage_provider = upload_res["storage_provider"]
                s3_bucket = upload_res["s3_bucket"]
                s3_url = upload_res["s3_url"]
            except Exception as e:
                logger.warning("Initial S3 upload deferred to worker: %s", e)

        # 7. Atomic DB Transaction for Document & Job.
        # The file is already on disk at this point, so a failed insert would
        # strand it. Any failure here removes what was written.
        try:
            with db.transaction() as conn:
                doc_record = self.doc_repo.create(
                    {
                        "uuid": doc_uuid,
                        "original_filename": clean_filename,
                        "stored_filename": stored_filename,
                        "file_extension": ext,
                        "mime_type": "application/pdf",
                        "file_size_bytes": file_size,
                        "file_hash": file_hash,
                        "page_count": page_count,
                        "status": DocumentStatus.UPLOADED.value,
                        "storage_provider": storage_provider,
                        "s3_bucket": s3_bucket,
                        "s3_key": s3_key,
                        "s3_url": s3_url,
                    },
                    conn=conn,
                )

                job_record = self.job_repo.create(
                    {
                        "job_uuid": job_uuid,
                        "document_id": doc_record["id"],
                        "job_type": "PDF_EXTRACTION",
                        "status": JobStatus.QUEUED.value,
                        "stage": JobStage.VALIDATION.value,
                        "priority": 0,
                        "total_pages": page_count,
                        "idempotency_key": idempotency_key,
                    },
                    conn=conn,
                )
        except Exception:
            # Roll the filesystem back so a failed insert leaves nothing behind.
            try:
                local_stored_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove orphaned upload at %s", local_stored_path)
            logger.error("Persisting document %s failed; removed staged file", doc_uuid)
            raise

        logger.info("Created document %s and queued job %s", doc_uuid, job_uuid)
        return {
            "document_id": doc_uuid,
            "job_id": job_uuid,
            "status": "queued",
            "is_duplicate": False,
            "message": "Document uploaded and processing job queued",
        }

    def get_document_by_uuid(self, doc_uuid: str) -> dict:
        doc = self.doc_repo.get_by_uuid(doc_uuid)
        if not doc:
            raise DocumentNotFoundError(doc_uuid)
        return doc

    def list_documents(
        self,
        limit: int = 25,
        offset: int = 0,
        status: Optional[str] = None,
        uuid: Optional[str] = None,
    ) -> dict:
        """Page through documents, each joined with the state of its latest job."""
        docs = self.doc_repo.list_documents(limit=limit, offset=offset, status=status, uuid=uuid)
        total = len(docs) if uuid else self.doc_repo.count_documents(status=status)

        items = []
        for doc in docs:
            job = self.job_repo.get_by_document_id(doc["id"])
            items.append(
                {
                    "uuid": doc["uuid"],
                    "original_filename": doc["original_filename"],
                    "file_size_bytes": doc["file_size_bytes"],
                    "page_count": doc["page_count"] or 0,
                    "status": doc["status"],
                    "storage_provider": doc["storage_provider"],
                    "extraction_method": doc["extraction_method"],
                    "text_character_count": doc["text_character_count"] or 0,
                    "word_count": doc["word_count"] or 0,
                    "processing_duration_ms": doc["processing_duration_ms"],
                    "uploaded_at": doc["uploaded_at"],
                    "job_id": job["job_uuid"] if job else None,
                    "job_status": job["status"].lower() if job else None,
                    "job_stage": job["stage"] if job else None,
                    "progress_percentage": round(job["progress_percentage"] or 0.0, 2) if job else 0.0,
                    "processed_pages": (job["processed_pages"] or 0) if job else 0,
                    "total_pages": (job["total_pages"] or 0) if job else 0,
                    "error_code": job["error_code"] if job else None,
                    "error_message": job["error_message"] if job else None,
                }
            )

        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get_document_pages(self, doc_uuid: str, limit: int = 1000, offset: int = 0) -> dict:
        """Per-page classification for a document, plus counts over all pages.

        The summary is computed across every page, not just the returned slice,
        so a caller can show the native/OCR split without paging through.
        """
        doc = self.get_document_by_uuid(doc_uuid)
        pages = self.page_repo.get_pages_by_document_id(doc["id"])

        summary = {
            "total": len(pages),
            "native_text": 0,
            "image_based": 0,
            "mixed": 0,
            "empty": 0,
            "ocr_pages": 0,
            "done": 0,
            "failed": 0,
            "pending": 0,
        }
        by_type = {
            "NATIVE_TEXT": "native_text",
            "IMAGE_BASED": "image_based",
            "MIXED": "mixed",
            "EMPTY": "empty",
        }
        for pg in pages:
            key = by_type.get(pg.get("page_type") or "")
            if key:
                summary[key] += 1
            if pg.get("ocr_used"):
                summary["ocr_pages"] += 1
            status = (pg.get("status") or "").upper()
            if status == "DONE":
                summary["done"] += 1
            elif status == "FAILED":
                summary["failed"] += 1
            else:
                summary["pending"] += 1

        window = pages[offset : offset + limit]
        items = [
            {
                "page_number": pg["page_number"],
                "page_type": pg["page_type"],
                "extraction_method": pg["extraction_method"],
                "status": pg["status"],
                "ocr_used": bool(pg["ocr_used"]),
                "has_text": bool(pg["has_text"]),
                "text_character_count": pg["text_character_count"] or 0,
                "text_density": pg["text_density"] or 0.0,
                "image_count": pg["image_count"] or 0,
                "image_area_ratio": pg["image_area_ratio"] or 0.0,
                "processing_time_ms": pg["processing_time_ms"] or 0,
                "error_code": pg["error_code"],
                "error_message": pg["error_message"],
            }
            for pg in window
        ]

        return {
            "items": items,
            "summary": summary,
            "total": len(pages),
            "limit": limit,
            "offset": offset,
        }

    def get_output_file(self, doc_uuid: str, file_type: str) -> Optional[dict]:
        """The recorded artifact row for a document, or None if never written."""
        doc = self.get_document_by_uuid(doc_uuid)
        return self.result_repo.get_output_file_by_type(doc["id"], file_type)

    def get_extracted_text_by_uuid(self, doc_uuid: str) -> dict:
        doc = self.get_document_by_uuid(doc_uuid)
        result = self.result_repo.get_extracted_text(doc["id"])
        if not result:
            return {
                "document_id": doc_uuid,
                "original_filename": doc["original_filename"],
                "text": "",
                "character_count": 0,
                "word_count": 0,
                "text_hash": "",
                "page_count": doc["page_count"],
                "extraction_method": doc["extraction_method"],
                "created_at": None,
            }
        return {
            "document_id": doc_uuid,
            "original_filename": doc["original_filename"],
            "text": result["text"],
            "character_count": result["character_count"],
            "word_count": result["word_count"],
            "text_hash": result["text_hash"],
            "page_count": doc["page_count"],
            "extraction_method": doc["extraction_method"],
            "created_at": result["created_at"],
        }


document_service = DocumentService()
