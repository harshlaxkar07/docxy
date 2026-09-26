from typing import Optional
from app.core.config import settings
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.log_repository import LogRepository
from app.core.logging import get_logger

logger = get_logger(__name__)


class RecoveryService:
    def __init__(
        self,
        job_repo: Optional[JobRepository] = None,
        log_repo: Optional[LogRepository] = None,
    ):
        self.job_repo = job_repo or JobRepository()
        self.log_repo = log_repo or LogRepository()

    def recover_stale_jobs(self) -> int:
        """Scan for abandoned/interrupted jobs with stale heartbeats and reset them to RETRYING or FAILED."""
        stale_jobs = self.job_repo.find_stale_jobs(settings.JOB_STALE_TIMEOUT_SECONDS)
        recovered_count = 0

        for job in stale_jobs:
            job_id = job["id"]
            job_uuid = job["job_uuid"]
            doc_id = job["document_id"]
            logger.warning(
                "Found stale job %s (last heartbeat: %s). Initiating crash recovery...",
                job_uuid,
                job.get("last_heartbeat_at"),
            )

            updated = self.job_repo.reset_stale_job(job_id, max_attempts=settings.JOB_MAX_ATTEMPTS)
            recovered_count += 1

            if updated:
                new_status = updated["status"]
                self.log_repo.create_log(
                    job_id=job_id,
                    document_id=doc_id,
                    level="WARNING",
                    event="job_recovered",
                    stage="crash_recovery",
                    message=f"Job {job_uuid} recovered from stale worker crash. Status set to {new_status}.",
                )
                logger.info("Job %s reset to status '%s'", job_uuid, new_status)

        return recovered_count


recovery_service = RecoveryService()
