import os
import signal
import sys
import threading
import time
import uuid
from typing import Optional

from app.core.config import settings
from app.db.repositories.job_repository import JobRepository
from app.workers.task_processor import task_processor
from app.workers.recovery import recovery_service
from app.core.logging import get_logger

logger = get_logger(__name__)


class BackgroundWorker:
    def __init__(
        self,
        worker_id: Optional[str] = None,
        job_repo: Optional[JobRepository] = None,
    ):
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.job_repo = job_repo or JobRepository()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start worker in a background daemon thread."""
        if self._running:
            return

        self._running = True
        logger.info("Starting background worker %s", self.worker_id)
        
        # Run startup crash recovery
        try:
            recovered = recovery_service.recover_stale_jobs()
            if recovered > 0:
                logger.info("Recovered %d stale jobs on worker startup", recovered)
        except Exception as e:
            logger.error("Startup recovery failed: %s", e)

        self._thread = threading.Thread(target=self._run_loop, name=f"WorkerThread-{self.worker_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal worker loop to stop gracefully."""
        if not self._running:
            return
        logger.info("Stopping background worker %s...", self.worker_id)
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("Background worker %s stopped.", self.worker_id)

    def _run_loop(self) -> None:
        """Main polling loop."""
        poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS

        while self._running:
            try:
                # 1. Attempt to claim next available job atomically
                job = self.job_repo.claim_next_job(self.worker_id)
                if not job:
                    time.sleep(poll_interval)
                    continue

                logger.info("Worker %s claimed job %s", self.worker_id, job["job_uuid"])

                # 2. Process claimed job
                task_processor.process_job(job)

            except Exception as e:
                logger.error("Worker %s loop encountered unexpected error: %s", self.worker_id, e, exc_info=True)
                time.sleep(poll_interval)


worker = BackgroundWorker()
