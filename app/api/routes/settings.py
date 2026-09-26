from fastapi import APIRouter
from app.core.config import settings
from app.schemas.common import ApiResponse
from app.schemas.settings import SafeSettingsResponse

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


@router.get("", response_model=ApiResponse[SafeSettingsResponse])
def get_safe_settings():
    """Retrieve safe, non-sensitive configuration settings."""
    return ApiResponse(
        success=True,
        data=SafeSettingsResponse(
            app_name=settings.APP_NAME,
            app_env=settings.APP_ENV,
            debug=settings.DEBUG,
            max_upload_size_mb=settings.MAX_UPLOAD_SIZE_MB,
            max_pages_per_document=settings.MAX_PAGES_PER_DOCUMENT,
            pdf_min_text_length=settings.PDF_MIN_TEXT_LENGTH,
            pdf_min_text_density=settings.PDF_MIN_TEXT_DENSITY,
            pdf_min_image_area_ratio=settings.PDF_MIN_IMAGE_AREA_RATIO,
            aws_enabled=settings.AWS_ENABLED,
            aws_region=settings.AWS_REGION,
            aws_s3_bucket=settings.AWS_S3_BUCKET,
            groq_enabled=settings.GROQ_ENABLED,
            groq_model=settings.GROQ_MODEL,
            groq_requests_per_second=settings.GROQ_REQUESTS_PER_SECOND,
            groq_requests_per_minute=settings.GROQ_REQUESTS_PER_MINUTE,
            groq_requests_per_day=settings.GROQ_REQUESTS_PER_DAY,
            groq_min_request_gap_seconds=settings.GROQ_MIN_REQUEST_GAP_SECONDS,
            worker_enabled=settings.WORKER_ENABLED,
            worker_count=settings.WORKER_COUNT,
            worker_poll_interval_seconds=settings.WORKER_POLL_INTERVAL_SECONDS,
            job_stale_timeout_seconds=settings.JOB_STALE_TIMEOUT_SECONDS,
            txt_include_page_markers=settings.TXT_INCLUDE_PAGE_MARKERS,
            txt_include_metadata=settings.TXT_INCLUDE_METADATA,
        ),
    )
