from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    id: int
    uuid: str
    original_filename: str
    file_size_bytes: int
    file_hash: str
    page_count: int
    status: str
    storage_provider: str
    s3_key: Optional[str] = None
    s3_url: Optional[str] = None
    uploaded_at: Optional[str] = None
    processing_duration_ms: Optional[int] = None
    extraction_method: Optional[str] = None
    text_character_count: int = 0
    word_count: int = 0


class DocumentUploadResponse(BaseModel):
    document_id: str
    job_id: str
    status: str
    is_duplicate: bool = False
    message: str = "Document uploaded and processing job queued"


class DocumentTextResponse(BaseModel):
    document_id: str
    original_filename: str
    text: str
    character_count: int
    word_count: int
    text_hash: str
    page_count: int
    extraction_method: Optional[str] = None
    created_at: Optional[str] = None


class DocumentListItem(BaseModel):
    """A document plus the state of its most recent processing job."""

    uuid: str
    original_filename: str
    file_size_bytes: int
    page_count: int
    status: str
    storage_provider: str
    extraction_method: Optional[str] = None
    text_character_count: int = 0
    word_count: int = 0
    processing_duration_ms: Optional[int] = None
    uploaded_at: Optional[str] = None
    job_id: Optional[str] = None
    job_status: Optional[str] = None
    job_stage: Optional[str] = None
    progress_percentage: float = 0.0
    processed_pages: int = 0
    total_pages: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int
    limit: int
    offset: int


class DocumentPageItem(BaseModel):
    """One row of document_pages: how a single page was classified and handled."""

    page_number: int
    page_type: str
    extraction_method: str
    status: str
    ocr_used: bool = False
    has_text: bool = False
    text_character_count: int = 0
    text_density: float = 0.0
    image_count: int = 0
    image_area_ratio: float = 0.0
    processing_time_ms: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class DocumentPageSummary(BaseModel):
    """Counts across every page of the document, not just the returned slice."""

    total: int = 0
    native_text: int = 0
    image_based: int = 0
    mixed: int = 0
    empty: int = 0
    ocr_pages: int = 0
    done: int = 0
    failed: int = 0
    pending: int = 0


class DocumentPagesResponse(BaseModel):
    items: list[DocumentPageItem]
    summary: DocumentPageSummary
    total: int
    limit: int
    offset: int
