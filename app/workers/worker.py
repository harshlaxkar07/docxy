import os
import signal
import threading
import uuid
from typing import Optional

from app.core import runtime_settings
from app.core.config import settings
from app.core.logging import get_logger
from app.db.repositories.job_repository import JobRepository
from app.workers.recovery import recovery_service
from app.workers.task_processor import task_processor

logger = get_logger(__name__)


class Heartbeat:
    """Bumps a job's heartbeat on a timer while the job runs.

    Previously the heartbeat was only bumped as each page completed, so a
    single OCR page slower than JOB_STALE_TIMEOUT_SECONDS made a healthy job
    look abandoned to the recovery sweep. A timer decouples liveness from the
    pace of individual pages.
    """

    def __init__(self, job_id: int, job_repo: JobRepository, interval: Optional[float] = None):
        self.job_id = job_id
        self.job_repo = job_repo
        self.interval = interval or settings.WORKER_HEARTBEAT_INTERVAL_SECONDS
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "Heartbeat":
        self._thread = threading.Thread(
            target=self._beat, name=f"Heartbeat-{self.job_id}", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _beat(self) -> None:
        while True:
            try:
                self.job_repo.update_heartbeat(self.job_id)
            except Exception as e:  # a failed beat must never kill the job
                logger.warning("Heartbeat failed for job %d: %s", self.job_id, e)
            if self._stop.wait(self.interval):
                return


class BackgroundWorker:
    """A single worker: claim a job, process it, repeat."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        job_repo: Optional[JobRepository] = None,
    ):
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.job_repo = job_repo or JobRepository()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"WorkerThread-{self.worker_id}", daemon=True
        )
        self._thread.start()
        logger.info("Started worker %s", self.worker_id)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run_loop(self) -> None:
        poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS

        while not self._stop.is_set():
            try:
                job = self.job_repo.claim_next_job(self.worker_id)
                if not job:
                    self._stop.wait(poll_interval)
                    continue

                logger.info("Worker %s claimed job %s", self.worker_id, job["job_uuid"])

                # A GROQ_API_KEY stored as a runtime override takes precedence
                # over the environment for this job.
                custom_key = runtime_settings.get("GROQ_API_KEY")

                # The heartbeat covers the whole job, independent of page pace.
                with Heartbeat(job["id"], self.job_repo):
                    task_processor.process_job(job, custom_groq_key=custom_key)

            except Exception as e:
                logger.error(
                    "Worker %s loop encountered unexpected error: %s",
                    self.worker_id,
                    e,
                    exc_info=True,
                )
                self._stop.wait(poll_interval)


class WorkerPool:
    """Runs WORKER_COUNT workers plus one periodic recovery sweeper.

    The claim query is already race-safe (a guarded UPDATE that yields no rows
    when another worker won), so workers scale without further coordination.
    """

    def __init__(self, count: Optional[int] = None):
        self.count = max(1, count if count is not None else settings.WORKER_COUNT)
        self.workers: list[BackgroundWorker] = []
        self._stop = threading.Event()
        self._sweeper: Optional[threading.Thread] = None
        self._signals_installed = False

    @property
    def is_running(self) -> bool:
        return any(w.is_running for w in self.workers)

    # Kept for callers that checked the old private flag.
    @property
    def _running(self) -> bool:
        return self.is_running

    def start(self) -> None:
        if self.is_running:
            return

        self._stop.clear()
        self.count = max(1, settings.WORKER_COUNT)

        # One sweep up front reclaims anything abandoned by a previous process.
        self._sweep(context="startup")

        self.workers = [BackgroundWorker() for _ in range(self.count)]
        for w in self.workers:
            w.start()

        self._sweeper = threading.Thread(
            target=self._sweep_loop, name="RecoverySweeper", daemon=True
        )
        self._sweeper.start()

        logger.info("Worker pool started with %d worker(s)", self.count)

    def stop(self) -> None:
        if not self.workers and not self._sweeper:
            return
        logger.info("Stopping worker pool (%d worker(s))...", len(self.workers))
        self._stop.set()
        for w in self.workers:
            w.stop()
        if self._sweeper and self._sweeper.is_alive():
            self._sweeper.join(timeout=3.0)
        self.workers = []
        self._sweeper = None
        logger.info("Worker pool stopped.")

    def _sweep(self, context: str) -> None:
        try:
            recovered = recovery_service.recover_stale_jobs()
            if recovered:
                logger.info("Recovered %d stale job(s) during %s sweep", recovered, context)
        except Exception as e:
            logger.error("Recovery sweep (%s) failed: %s", context, e)

    def _sweep_loop(self) -> None:
        """Re-sweep on an interval so a job orphaned mid-run is reclaimed."""
        interval = settings.RECOVERY_SWEEP_INTERVAL_SECONDS
        while not self._stop.wait(interval):
            self._sweep(context="periodic")

    def install_signal_handlers(self) -> None:
        """Stop the pool cleanly on SIGTERM/SIGINT.

        Only valid on the main thread. Any existing handler (uvicorn's) is
        still invoked afterwards, so normal shutdown is unaffected.
        """
        if self._signals_installed or threading.current_thread() is not threading.main_thread():
            return

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                previous = signal.getsignal(sig)
            except (ValueError, OSError):
                continue

            def handler(signum, frame, _previous=previous):
                logger.info("Received signal %s — stopping worker pool", signum)
                self.stop()
                if callable(_previous) and _previous not in (signal.SIG_IGN, signal.SIG_DFL):
                    _previous(signum, frame)

            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                continue

        self._signals_installed = True


worker = WorkerPool()
