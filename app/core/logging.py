import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Optional
from app.core.config import settings

# Sensitive patterns to redact
SECRET_PATTERNS = [
    re.compile(r'(?i)(gsk_[a-zA-Z0-9_-]{20,})'),
    re.compile(r'(?i)(AKIA[0-9A-Z]{16})'),
    re.compile(r'(?i)(aws_secret_access_key\s*=\s*[\'"][^\'"]+[\'"])'),
    re.compile(r'(?i)(bearer\s+[a-zA-Z0-9_\-\.]{20,})'),
    re.compile(r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{16,}["\']?)'),
]


class SecretMaskingFilter(logging.Filter):
    """Filter that masks sensitive tokens, API keys, and credentials from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._mask_val(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._mask_val(v) for v in record.args)
        return True

    @classmethod
    def mask_secrets(cls, text: str) -> str:
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[REDACTED_SECRET]", text)
        return text

    @classmethod
    def _mask_val(cls, val: object) -> object:
        if isinstance(val, str):
            return cls.mask_secrets(val)
        return val


class ContextFormatter(logging.Formatter):
    """Formatter that attaches correlation IDs if present in record attributes."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = getattr(record, "request_id", "-")
        job_id = getattr(record, "job_id", "-")
        doc_id = getattr(record, "document_id", "-")
        record.correlation = f"[req:{req_id} job:{job_id} doc:{doc_id}]"
        return super().format(record)


def setup_logging() -> None:
    """Configures application, worker, error, and audit logging."""
    settings.ensure_directories()
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    if settings.DEBUG:
        log_level = logging.DEBUG

    formatter = ContextFormatter(
        "%(asctime)s [%(levelname)s] %(correlation)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    secret_filter = SecretMaskingFilter()

    # Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(secret_filter)
    root_logger.addHandler(console_handler)

    # application.log handler
    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "application.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(log_level)
    app_handler.setFormatter(formatter)
    app_handler.addFilter(secret_filter)
    root_logger.addHandler(app_handler)

    # error.log handler (WARNING and above)
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)
    error_handler.addFilter(secret_filter)
    root_logger.addHandler(error_handler)

    # worker.log handler
    worker_logger = logging.getLogger("app.workers")
    worker_handler = logging.handlers.RotatingFileHandler(
        log_dir / "worker.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    worker_handler.setLevel(log_level)
    worker_handler.setFormatter(formatter)
    worker_handler.addFilter(secret_filter)
    worker_logger.addHandler(worker_handler)

    # audit.log handler
    audit_logger = logging.getLogger("app.audit")
    audit_handler = logging.handlers.RotatingFileHandler(
        log_dir / "audit.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    audit_handler.setLevel(logging.INFO)
    audit_handler.setFormatter(formatter)
    audit_handler.addFilter(secret_filter)
    audit_logger.addHandler(audit_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
