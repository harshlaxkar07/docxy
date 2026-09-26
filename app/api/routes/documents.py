import os
import tempfile
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Header, Query, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse

from app.schemas.common import ApiResponse
from app.schemas.document import (
    DocumentResponse,
    DocumentUploadResponse,
    DocumentTextResponse,
    DocumentListResponse,
    DocumentListItem,
    DocumentPagesResponse,
    DocumentPageItem,
    DocumentPageSummary,
)
from app.services.document_service import document_service
from app.services.s3_service import s3_service
from app.core.config import settings
from app.core.exceptions import PDFTooLargeError

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])


UPLOAD_CHUNK_BYTES = 1024 * 1024


@router.post("", response_model=ApiResponse[DocumentUploadResponse], status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(..., description="PDF document to upload and extract"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Upload a PDF document. Returns immediately with document_id and job_id for background processing."""
    # The body is streamed to disk a chunk at a time and aborted the moment it
    # exceeds the limit, so an oversized upload never accumulates in memory.
    max_bytes = settings.max_upload_size_bytes
    Path(settings.TEMP_DIR).mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(suffix=".pdf", dir=settings.TEMP_DIR)
    tmp_path = Path(tmp_name)
    received = 0
    try:
        with os.fdopen(fd, "wb") as staged:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                received += len(chunk)
                if received > max_bytes:
                    raise PDFTooLargeError(
                        f"Upload exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit"
                    )
                staged.write(chunk)

        result = document_service.process_upload(
            file_path=tmp_path,
            original_filename=file.filename or "uploaded.pdf",
            content_type=file.content_type,
            idempotency_key=idempotency_key,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return ApiResponse(
        success=True,
        data=DocumentUploadResponse(
            document_id=result["document_id"],
            job_id=result["job_id"],
            status=result["status"],
            is_duplicate=result["is_duplicate"],
            message=result["message"],
        ),
    )


@router.get("", response_model=ApiResponse[DocumentListResponse])
def list_documents(
    limit: int = Query(25, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    doc_status: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by document status (UPLOADED, PROCESSING, COMPLETED, FAILED)",
    ),
    uuid: Optional[str] = Query(
        None,
        description="Return only the document with this UUID, joined with its job",
    ),
):
    """List documents newest-first, each joined with its latest job state."""
    result = document_service.list_documents(
        limit=limit, offset=offset, status=doc_status, uuid=uuid
    )
    return ApiResponse(
        success=True,
        data=DocumentListResponse(
            items=[DocumentListItem(**i) for i in result["items"]],
            total=result["total"],
            limit=result["limit"],
            offset=result["offset"],
        ),
    )


@router.get("/{document_id}", response_model=ApiResponse[DocumentResponse])
def get_document(document_id: str):
    """Get metadata for a specific document."""
    doc = document_service.get_document_by_uuid(document_id)
    return ApiResponse(
        success=True,
        data=DocumentResponse(**doc),
    )


@router.get("/{document_id}/text", response_model=ApiResponse[DocumentTextResponse])
def get_extracted_text(document_id: str):
    """Get extracted text for a completed document."""
    text_data = document_service.get_extracted_text_by_uuid(document_id)
    return ApiResponse(
        success=True,
        data=DocumentTextResponse(**text_data),
    )


@router.get("/{document_id}/pages", response_model=ApiResponse[DocumentPagesResponse])
def get_document_pages(
    document_id: str,
    limit: int = Query(1000, ge=1, le=5000, description="Page rows to return"),
    offset: int = Query(0, ge=0),
):
    """Per-page classification and extraction method for a document."""
    result = document_service.get_document_pages(document_id, limit=limit, offset=offset)
    return ApiResponse(
        success=True,
        data=DocumentPagesResponse(
            items=[DocumentPageItem(**i) for i in result["items"]],
            summary=DocumentPageSummary(**result["summary"]),
            total=result["total"],
            limit=result["limit"],
            offset=result["offset"],
        ),
    )


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    file_type: str = Query("txt", enum=["pdf", "txt"], description="File type to download ('pdf' or 'txt')"),
):
    """Download the original PDF or generated extracted TXT file."""
    doc = document_service.get_document_by_uuid(document_id)

    if file_type == "pdf":
        return _serve_artifact(
            doc=doc,
            file_type="ORIGINAL_PDF",
            stored_key=doc.get("s3_key"),
            local_fallbacks=[Path(settings.LOCAL_STORAGE_DIR) / doc["stored_filename"]],
            download_name=doc["original_filename"],
            media_type="application/pdf",
            missing_detail="Original PDF file not found in storage",
        )

    return _serve_artifact(
        doc=doc,
        file_type="EXTRACTED_TXT",
        stored_key=None,
        local_fallbacks=[],
        download_name=f"{Path(doc['original_filename']).stem}_extracted.txt",
        media_type="text/plain; charset=utf-8",
        missing_detail="Extracted text file not yet generated",
    )


def _serve_artifact(
    doc: dict,
    file_type: str,
    stored_key: Optional[str],
    local_fallbacks: list[Path],
    download_name: str,
    media_type: str,
    missing_detail: str,
):
    """Resolve an artifact by the key recorded when it was written.

    The key comes from output_files rather than being rebuilt from today's
    date — a recomputed `extracted/YYYY/MM/...` key silently misses every file
    written in an earlier month.
    """
    record = document_service.get_output_file(doc["uuid"], file_type)
    key = (record or {}).get("s3_key") or stored_key

    if settings.AWS_ENABLED:
        if not key:
            raise HTTPException(status_code=404, detail=missing_detail)
        return RedirectResponse(url=s3_service.generate_presigned_url(key))

    candidates = []
    if key:
        candidates.append(Path(settings.LOCAL_STORAGE_DIR) / key)
    candidates.extend(local_fallbacks)

    for path in candidates:
        if path.exists():
            return FileResponse(path=str(path), filename=download_name, media_type=media_type)

    raise HTTPException(status_code=404, detail=missing_detail)
