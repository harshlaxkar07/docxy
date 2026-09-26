from typing import Optional
from app.constants.errors import ErrorCode


class AppException(Exception):
    """Base exception for application errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_SERVER_ERROR,
        status_code: int = 500,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}


class PDFValidationError(AppException):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.INVALID_PDF_FORMAT,
            status_code=400,
            details=details,
        )


class PDFCorruptedError(AppException):
    def __init__(self, message: str = "PDF file is corrupted or unreadable", details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.PDF_CORRUPTED,
            status_code=400,
            details=details,
        )


class PDFEncryptedError(AppException):
    def __init__(self, message: str = "Password-protected or encrypted PDFs are not supported", details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.PDF_ENCRYPTED,
            status_code=400,
            details=details,
        )


class PDFTooLargeError(AppException):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.FILE_TOO_LARGE,
            status_code=413,
            details=details,
        )


class PDFPageLimitError(AppException):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.EXCEEDS_PAGE_LIMIT,
            status_code=400,
            details=details,
        )


class JobNotFoundError(AppException):
    def __init__(self, job_id: str):
        super().__init__(
            message=f"Job with ID '{job_id}' not found",
            error_code=ErrorCode.JOB_NOT_FOUND,
            status_code=404,
            details={"job_id": job_id},
        )


class DocumentNotFoundError(AppException):
    def __init__(self, document_id: str):
        super().__init__(
            message=f"Document with ID '{document_id}' not found",
            error_code=ErrorCode.NOT_FOUND,
            status_code=404,
            details={"document_id": document_id},
        )


class JobStateError(AppException):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.INVALID_STATE_TRANSITION,
            status_code=409,
            details=details,
        )


class JobAlreadyRunningError(AppException):
    def __init__(self, job_id: str):
        super().__init__(
            message=f"Job '{job_id}' is already running or completed",
            error_code=ErrorCode.JOB_ALREADY_RUNNING,
            status_code=409,
            details={"job_id": job_id},
        )


class StorageError(AppException):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.STORAGE_ERROR,
            status_code=500,
            details=details,
        )


class S3UploadError(StorageError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message=message, details=details)
        self.error_code = ErrorCode.S3_UPLOAD_ERROR


class S3DownloadError(StorageError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message=message, details=details)
        self.error_code = ErrorCode.S3_DOWNLOAD_ERROR


class S3ConfigError(StorageError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message=message, details=details)
        self.error_code = ErrorCode.S3_CONFIG_ERROR



class GroqAPIError(AppException):
    def __init__(self, message: str, status_code: int = 502, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.GROQ_API_ERROR,
            status_code=status_code,
            details=details,
        )


class GroqRateLimitError(GroqAPIError):
    def __init__(self, message: str, retry_after: Optional[int] = None, details: Optional[dict] = None):
        super().__init__(
            message=message,
            status_code=429,
            details={"retry_after": retry_after, **(details or {})},
        )
        self.error_code = ErrorCode.GROQ_RATE_LIMITED
        self.retry_after = retry_after


class GroqTimeoutError(GroqAPIError):
    def __init__(self, message: str = "Groq Vision API request timed out", details: Optional[dict] = None):
        super().__init__(
            message=message,
            status_code=504,
            details=details,
        )
        self.error_code = ErrorCode.GROQ_TIMEOUT


class ConfigurationError(AppException):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=500,
            details=details,
        )
