import os
import shutil
import contextlib
from pathlib import Path
from typing import Generator, Optional
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class TempManager:
    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = Path(temp_dir or settings.TEMP_DIR)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def get_job_dir(self, job_uuid: str) -> Path:
        """Return dedicated temporary directory for a specific job."""
        job_dir = self.temp_dir / job_uuid
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def cleanup_job_dir(self, job_uuid: str) -> None:
        """Safely remove dedicated temporary directory for a job."""
        job_dir = self.temp_dir / job_uuid
        if job_dir.exists() and job_dir.is_dir():
            try:
                shutil.rmtree(job_dir, ignore_errors=True)
                logger.debug("Cleaned up temp directory for job %s", job_uuid)
            except Exception as e:
                logger.warning("Failed to clean temp directory %s: %s", job_dir, e)

    @contextlib.contextmanager
    def job_temp_context(self, job_uuid: str) -> Generator[Path, None, None]:
        """Context manager creating and auto-cleaning a job's temp directory."""
        job_dir = self.get_job_dir(job_uuid)
        try:
            yield job_dir
        finally:
            self.cleanup_job_dir(job_uuid)

    def cleanup_all_temp(self) -> None:
        """Clean all files in temp_dir on shutdown/startup."""
        if self.temp_dir.exists():
            for item in self.temp_dir.iterdir():
                if item.name == ".gitkeep":
                    continue
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning("Failed to remove temp file %s: %s", item, e)


temp_manager = TempManager()
