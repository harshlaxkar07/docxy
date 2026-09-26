from typing import Optional
from pydantic import BaseModel


class SafeSettingsResponse(BaseModel):
    app_name: str
    app_env: str
    debug: bool
    max_upload_size_mb: int
    max_pages_per_document: int
    pdf_min_text_length: int
    pdf_min_text_density: float
    pdf_min_image_area_ratio: float
    aws_enabled: bool
    aws_region: str
    aws_s3_bucket: str
    groq_enabled: bool
    groq_model: str
    groq_requests_per_second: int
    groq_requests_per_minute: int
    groq_requests_per_day: int
    groq_min_request_gap_seconds: float
    worker_enabled: bool
    worker_count: int
    worker_poll_interval_seconds: float
    job_stale_timeout_seconds: float
    txt_include_page_markers: bool
    txt_include_metadata: bool
