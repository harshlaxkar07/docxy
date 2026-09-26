from typing import Optional
from fastapi import APIRouter, Query, status

from app.schemas.common import ApiResponse
from app.schemas.job import JobResponse, JobLogResponse
from app.services.job_service import job_service

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


@router.get("/{job_id}", response_model=ApiResponse[JobResponse])
def get_job_status(job_id: str):
    """Get persistent processing job status, stage, progress, and page counts."""
    job_data = job_service.get_job_by_uuid(job_id)
    return ApiResponse(
        success=True,
        data=JobResponse(**job_data),
    )


@router.get("/{job_id}/logs", response_model=ApiResponse[list[JobLogResponse]])
def get_job_logs(
    job_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get audit and lifecycle logs for a specific job."""
    logs = job_service.get_job_logs(job_id, limit=limit, offset=offset)
    return ApiResponse(
        success=True,
        data=[JobLogResponse(**l) for l in logs],
    )


@router.post("/{job_id}/retry", response_model=ApiResponse[JobResponse])
def retry_job(job_id: str):
    """Manually retry a failed processing job."""
    job_data = job_service.retry_job(job_id)
    return ApiResponse(
        success=True,
        data=JobResponse(**job_data),
    )


@router.post("/{job_id}/cancel", response_model=ApiResponse[JobResponse])
def cancel_job(job_id: str):
    """Cancel an active or queued processing job."""
    job_data = job_service.cancel_job(job_id)
    return ApiResponse(
        success=True,
        data=JobResponse(**job_data),
    )
