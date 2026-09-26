from typing import Optional, Any
from pydantic import BaseModel, Field


class JobResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    stage: str
    progress_percentage: float
    processed_pages: int
    total_pages: int
    duration_ms: Optional[int] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class JobLogResponse(BaseModel):
    id: int
    level: str
    stage: Optional[str] = None
    event: str
    message: str
    metadata: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None
