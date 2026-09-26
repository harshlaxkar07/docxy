import json
from typing import Optional
from app.constants.statuses import JobStatus, JobStage
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.log_repository import LogRepository
from app.core.exceptions import JobNotFoundError, JobStateError
from app.core.logging import get_logger

logger = get_logger(__name__)


class JobService:
    def __init__(
        self,
        job_repo: Optional[JobRepository] = None,
        doc_repo: Optional[DocumentRepository] = None,
        log_repo: Optional[LogRepository] = None,
    ):
        self.job_repo = job_repo or JobRepository()
        self.doc_repo = doc_repo or DocumentRepository()
        self.log_repo = log_repo or LogRepository()

    def get_job_by_uuid(self, job_uuid: str) -> dict:
        job = self.job_repo.get_by_uuid(job_uuid)
        if not job:
            raise JobNotFoundError(job_uuid)
        doc = self.doc_repo.get_by_id(job["document_id"])
        return {
            "job_id": job["job_uuid"],
            "document_id": doc["uuid"] if doc else "",
            "status": job["status"].lower(),
            "stage": job["stage"],
            "progress_percentage": round(job["progress_percentage"] or 0.0, 2),
            "processed_pages": job["processed_pages"] or 0,
            "total_pages": job["total_pages"] or 0,
            "duration_ms": job["duration_ms"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "error_code": job["error_code"],
            "error_message": job["error_message"],
        }

    def get_job_logs(self, job_uuid: str, limit: int = 100, offset: int = 0) -> list[dict]:
        job = self.job_repo.get_by_uuid(job_uuid)
        if not job:
            raise JobNotFoundError(job_uuid)
        raw_logs = self.log_repo.get_logs_by_job(job["id"], limit=limit, offset=offset)
        formatted = []
        for l in raw_logs:
            meta = json.loads(l["metadata_json"]) if l.get("metadata_json") else None
            formatted.append(
                {
                    "id": l["id"],
                    "level": l["level"],
                    "stage": l["stage"],
                    "event": l["event"],
                    "message": l["message"],
                    "metadata": meta,
                    "created_at": l["created_at"],
                }
            )
        return formatted

    def retry_job(self, job_uuid: str) -> dict:
        job = self.job_repo.get_by_uuid(job_uuid)
        if not job:
            raise JobNotFoundError(job_uuid)
        current_status = JobStatus(job["status"])
        if current_status not in (JobStatus.FAILED, JobStatus.RETRYING):
            raise JobStateError(f"Cannot retry job in '{current_status.value}' state. Only FAILED jobs can be retried.")

        updated = self.job_repo.update_status(
            job["id"],
            JobStatus.QUEUED,
            stage=JobStage.VALIDATION,
            error_code=None,
            error_message=None,
        )
        self.log_repo.create_log(
            job_id=job["id"],
            document_id=job["document_id"],
            level="INFO",
            event="job_manual_retry",
            stage="manual_retry",
            message=f"Job {job_uuid} manually reset to QUEUED for retry.",
        )
        return self.get_job_by_uuid(job_uuid)

    def cancel_job(self, job_uuid: str) -> dict:
        job = self.job_repo.get_by_uuid(job_uuid)
        if not job:
            raise JobNotFoundError(job_uuid)
        current_status = JobStatus(job["status"])
        if current_status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
            raise JobStateError(f"Job is already in terminal state '{current_status.value}'")

        updated = self.job_repo.update_status(
            job["id"],
            JobStatus.CANCELLED,
            stage=JobStage.FAILED,
            error_code="JOB_CANCELLED",
            error_message="Job was cancelled by user request",
        )
        self.log_repo.create_log(
            job_id=job["id"],
            document_id=job["document_id"],
            level="WARNING",
            event="job_cancelled",
            stage="cancellation",
            message=f"Job {job_uuid} cancelled by user request.",
        )
        return self.get_job_by_uuid(job_uuid)


job_service = JobService()
