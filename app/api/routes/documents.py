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

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])


@router.post("", response_model=ApiResponse[DocumentUploadResponse], status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(..., description="PDF document to upload and extract"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Upload a PDF document. Returns immediately with document_id and job_id for background processing."""
    file_bytes = await file.read()
    result = document_service.process_upload(
        file_bytes=file_bytes,
        original_filename=file.filename or "uploaded.pdf",
        content_type=file.content_type,
        idempotency_key=idempotency_key,
    )
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
    doc_uuid = doc["uuid"]

    if file_type == "pdf":
        if doc.get("s3_key") and settings.AWS_ENABLED:
            presigned = s3_service.generate_presigned_url(doc["s3_key"])
            return RedirectResponse(url=presigned)
        else:
            local_path = Path(settings.LOCAL_STORAGE_DIR) / doc["stored_filename"]
            if not local_path.exists():
                raise HTTPException(status_code=404, detail="Original PDF file not found on disk")
            return FileResponse(
                path=str(local_path),
                filename=doc["original_filename"],
                media_type="application/pdf",
            )
    else:
        # Extracted TXT
        txt_s3_key = s3_service.generate_canonical_key("extracted", doc_uuid, "extracted.txt")
        if settings.AWS_ENABLED:
            presigned = s3_service.generate_presigned_url(txt_s3_key)
            return RedirectResponse(url=presigned)
        else:
            local_txt_path = Path(settings.LOCAL_STORAGE_DIR) / txt_s3_key
            if not local_txt_path.exists():
                # Fallback check for flat filename
                alt_path = Path(settings.LOCAL_STORAGE_DIR) / f"{Path(doc['original_filename']).stem}_extracted.txt"
                if alt_path.exists():
                    local_txt_path = alt_path
                else:
                    raise HTTPException(status_code=404, detail="Extracted text file not yet generated or not found")
            return FileResponse(
                path=str(local_txt_path),
                filename=f"{Path(doc['original_filename']).stem}_extracted.txt",
                media_type="text/plain; charset=utf-8",
            )
