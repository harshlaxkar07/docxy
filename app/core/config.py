import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application Configuration
    APP_NAME: str = "PDF Extraction Service"
    APP_ENV: str = "development"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Base Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATABASE_PATH: str = "./data/app.db"
    LOG_DIR: str = "./logs"
    DATA_DIR: str = "./data"
    TEMP_DIR: str = "./data/temp"
    LOCAL_STORAGE_DIR: str = "./data/output"

    # Security
    # Auth is opt-in so the service still starts with no configuration. Turn it
    # on and set API_KEYS before exposing this beyond localhost.
    AUTH_ENABLED: bool = False
    API_KEYS: str = ""
    API_KEY_HEADER: str = "X-API-Key"
    # Comma-separated origins, or "*" for any. Credentials are only permitted
    # when an explicit list is given: browsers reject "*" plus credentials.
    CORS_ALLOW_ORIGINS: str = "*"
    CORS_ALLOW_CREDENTIALS: bool = False

    # Processing Limits & Validation
    MAX_UPLOAD_SIZE_MB: int = 100
    MAX_PAGES_PER_DOCUMENT: int = 1000
    PDF_MIN_TEXT_LENGTH: int = 200
    PDF_MIN_TEXT_DENSITY: float = 0.005
    PDF_MIN_IMAGE_AREA_RATIO: float = 0.35

    # Storage Configuration (AWS S3 & Local Fallback)
    AWS_ENABLED: bool = False
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_S3_BUCKET: str = "pdf-processing-bucket"
    S3_PRESIGNED_EXPIRATION_SECONDS: int = 3600

    # Groq Vision Provider Configuration
    GROQ_ENABLED: bool = False
    GROQ_API_KEY: Optional[str] = None
    # Vision-capable Groq model. The old llama-3.2-*-vision-preview ids were
    # retired; a retired id fails with model_not_found at call time.
    GROQ_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    GROQ_REQUESTS_PER_SECOND: int = 1
    GROQ_REQUESTS_PER_MINUTE: int = 20
    GROQ_REQUESTS_PER_HOUR: int = 500
    GROQ_REQUESTS_PER_DAY: int = 1000
    GROQ_MIN_REQUEST_GAP_SECONDS: float = 2.0
    GROQ_MAX_RETRIES: int = 3
    GROQ_TIMEOUT_SECONDS: float = 30.0

    # Background Worker & Recovery
    WORKER_ENABLED: bool = True
    WORKER_COUNT: int = 1
    WORKER_POLL_INTERVAL_SECONDS: float = 2.0
    WORKER_HEARTBEAT_INTERVAL_SECONDS: float = 10.0
    JOB_STALE_TIMEOUT_SECONDS: float = 120.0
    JOB_MAX_ATTEMPTS: int = 3
    # How often the pool re-sweeps for stale jobs while running. A sweep only
    # at startup leaves a job orphaned mid-run stuck until the next restart.
    RECOVERY_SWEEP_INTERVAL_SECONDS: float = 60.0

    # Output Configuration
    TXT_INCLUDE_PAGE_MARKERS: bool = True
    TXT_INCLUDE_METADATA: bool = True

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_TO_DATABASE: bool = True

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def api_key_set(self) -> set[str]:
        """Accepted API keys, parsed from the comma-separated API_KEYS value."""
        return {k.strip() for k in self.API_KEYS.split(",") if k.strip()}

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()] or ["*"]

    @property
    def cors_allow_credentials(self) -> bool:
        """Credentials cannot be combined with a wildcard origin."""
        return self.CORS_ALLOW_CREDENTIALS and "*" not in self.cors_origins

    def ensure_directories(self) -> None:
        """Ensure runtime directories exist."""
        for path in [
            self.LOG_DIR,
            self.DATA_DIR,
            self.TEMP_DIR,
            self.LOCAL_STORAGE_DIR,
            os.path.dirname(self.DATABASE_PATH),
        ]:
            if path:
                Path(path).mkdir(parents=True, exist_ok=True)


settings = Settings()
