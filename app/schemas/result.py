"""Schemas for extraction results and produced artifacts.

Listed as delivered in OpenSpec task 7.3 but never written; these are the
response models for the extracted-text record and the output files a job
produces.
"""

from typing import Optional

from pydantic import BaseModel


class ExtractedTextResult(BaseModel):
    """A document's aggregated extracted text record."""

    document_id: int
    job_id: Optional[int] = None
    text: str
    character_count: int = 0
    word_count: int = 0
    text_hash: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class OutputFileResult(BaseModel):
    """One artifact produced by a job (ORIGINAL_PDF or EXTRACTED_TXT)."""

    id: int
    document_id: int
    job_id: Optional[int] = None
    file_type: str
    filename: str
    mime_type: str
    file_size_bytes: int
    s3_bucket: Optional[str] = None
    s3_key: Optional[str] = None
    s3_url: Optional[str] = None
    created_at: Optional[str] = None


class PageExtractionResult(BaseModel):
    """The outcome of extracting a single page."""

    page_number: int
    page_type: str
    extraction_method: str
    status: str
    ocr_used: bool = False
    text_character_count: int = 0
    processing_time_ms: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
