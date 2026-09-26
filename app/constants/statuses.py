from enum import Enum


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PROCESSING = "PROCESSING"
    OCR_PENDING = "OCR_PENDING"
    OCR_PROCESSING = "OCR_PROCESSING"
    GENERATING_TEXT = "GENERATING_TEXT"
    UPLOADING = "UPLOADING"
    DONE = "DONE"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"


class JobStage(str, Enum):
    VALIDATION = "validation"
    S3_UPLOAD_ORIGINAL = "s3_upload_original"
    PAGE_INSPECTION = "page_inspection"
    NATIVE_EXTRACTION = "native_extraction"
    OCR_PROCESSING = "ocr_processing"
    TEXT_AGGREGATION = "text_aggregation"
    TXT_GENERATION = "txt_generation"
    S3_UPLOAD_TXT = "s3_upload_txt"
    COMPLETED = "completed"
    FAILED = "failed"


class PageType(str, Enum):
    NATIVE_TEXT = "NATIVE_TEXT"
    IMAGE_BASED = "IMAGE_BASED"
    MIXED = "MIXED"
    EMPTY = "EMPTY"


class PageStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExtractionMethod(str, Enum):
    NATIVE = "NATIVE"
    OCR_GROQ = "OCR_GROQ"
    NONE = "NONE"


class StorageProvider(str, Enum):
    S3 = "S3"
    LOCAL = "LOCAL"


# Valid State Machine Transitions for Jobs
VALID_JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {
        JobStatus.RUNNING,
        JobStatus.PROCESSING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.RUNNING: {
        JobStatus.PROCESSING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.RETRYING,
    },
    JobStatus.PROCESSING: {
        JobStatus.OCR_PENDING,
        JobStatus.OCR_PROCESSING,
        JobStatus.GENERATING_TEXT,
        JobStatus.UPLOADING,
        JobStatus.DONE,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.RETRYING,
    },
    JobStatus.OCR_PENDING: {
        JobStatus.OCR_PROCESSING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.OCR_PROCESSING: {
        JobStatus.PROCESSING,
        JobStatus.GENERATING_TEXT,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.RETRYING,
    },
    JobStatus.GENERATING_TEXT: {
        JobStatus.UPLOADING,
        JobStatus.DONE,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.UPLOADING: {
        JobStatus.DONE,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.RETRYING: {
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.PROCESSING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.DONE: set(),
    JobStatus.FAILED: {JobStatus.RETRYING, JobStatus.QUEUED},
    JobStatus.CANCELLED: set(),
}


def is_valid_job_transition(current: JobStatus, target: JobStatus) -> bool:
    """Check if transitioning from current to target status is permitted."""
    if current == target:
        return True
    return target in VALID_JOB_TRANSITIONS.get(current, set())
