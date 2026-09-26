from fastapi import APIRouter, HTTPException

from app.core import runtime_settings
from app.core.config import settings
from app.db.repositories.settings_repository import (
    MUTABLE_KEYS,
    SECRET_KEYS,
    settings_repository,
)
from app.schemas.common import ApiResponse
from app.schemas.settings import (
    SafeSettingsResponse,
    RuntimeSettingValue,
    RuntimeSettingsResponse,
    RuntimeSettingUpdate,
)

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
            pdf_min_text_length=runtime_settings.get("PDF_MIN_TEXT_LENGTH"),
            pdf_min_text_density=runtime_settings.get("PDF_MIN_TEXT_DENSITY"),
            pdf_min_image_area_ratio=runtime_settings.get("PDF_MIN_IMAGE_AREA_RATIO"),
            aws_enabled=settings.AWS_ENABLED,
            aws_region=settings.AWS_REGION,
            aws_s3_bucket=settings.AWS_S3_BUCKET,
            groq_enabled=runtime_settings.get("GROQ_ENABLED"),
            groq_model=runtime_settings.get("GROQ_MODEL"),
            groq_requests_per_second=settings.GROQ_REQUESTS_PER_SECOND,
            groq_requests_per_minute=settings.GROQ_REQUESTS_PER_MINUTE,
            groq_requests_per_day=settings.GROQ_REQUESTS_PER_DAY,
            groq_min_request_gap_seconds=settings.GROQ_MIN_REQUEST_GAP_SECONDS,
            worker_enabled=settings.WORKER_ENABLED,
            worker_count=settings.WORKER_COUNT,
            worker_poll_interval_seconds=settings.WORKER_POLL_INTERVAL_SECONDS,
            job_stale_timeout_seconds=settings.JOB_STALE_TIMEOUT_SECONDS,
            txt_include_page_markers=runtime_settings.get("TXT_INCLUDE_PAGE_MARKERS"),
            txt_include_metadata=runtime_settings.get("TXT_INCLUDE_METADATA"),
        ),
    )


@router.get("/runtime", response_model=ApiResponse[RuntimeSettingsResponse])
def get_runtime_settings():
    """Tunable settings with their effective values and override state."""
    stored = settings_repository.get_all(include_secrets=False)
    items = [
        RuntimeSettingValue(
            key=key,
            value=runtime_settings.get(key),
            value_type=value_type,
            overridden=key in stored,
        )
        for key, value_type in MUTABLE_KEYS.items()
        if key not in SECRET_KEYS
    ]
    return ApiResponse(success=True, data=RuntimeSettingsResponse(items=items))


@router.put("/runtime/{key}", response_model=ApiResponse[RuntimeSettingValue])
def set_runtime_setting(key: str, payload: RuntimeSettingUpdate):
    """Override a tunable setting without restarting the service."""
    if key not in MUTABLE_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"'{key}' is not runtime-configurable. Allowed: {sorted(MUTABLE_KEYS)}",
        )
    settings_repository.set(key, payload.value, value_type=MUTABLE_KEYS[key])
    runtime_settings.invalidate()
    return ApiResponse(
        success=True,
        data=RuntimeSettingValue(
            key=key, value=runtime_settings.get(key),
            value_type=MUTABLE_KEYS[key], overridden=True,
        ),
    )


@router.delete("/runtime/{key}", response_model=ApiResponse[RuntimeSettingValue])
def clear_runtime_setting(key: str):
    """Remove an override so the environment value applies again."""
    if key not in MUTABLE_KEYS:
        raise HTTPException(status_code=400, detail=f"'{key}' is not runtime-configurable")
    settings_repository.delete(key)
    runtime_settings.invalidate()
    return ApiResponse(
        success=True,
        data=RuntimeSettingValue(
            key=key, value=runtime_settings.get(key),
            value_type=MUTABLE_KEYS[key], overridden=False,
        ),
    )
