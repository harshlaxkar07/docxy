import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union, BinaryIO
from app.core.config import settings
from app.core.exceptions import S3UploadError, S3DownloadError, S3ConfigError
from app.core.logging import get_logger

logger = get_logger(__name__)


class S3Service:
    def __init__(self):
        self.enabled = settings.AWS_ENABLED
        self.region = settings.AWS_REGION
        self.bucket = settings.AWS_S3_BUCKET
        self.local_dir = Path(settings.LOCAL_STORAGE_DIR)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._s3_client = None

        if self.enabled:
            self._init_client()

    def _init_client(self) -> None:
        try:
            import boto3
            from botocore.config import Config

            config = Config(
                region_name=self.region,
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=30,
            )
            client_kwargs = {
                "service_name": "s3",
                "region_name": self.region,
                "config": config,
            }
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

            self._s3_client = boto3.client(**client_kwargs)
            logger.info("Initialized AWS S3 client for bucket '%s' in region '%s'", self.bucket, self.region)
        except Exception as e:
            logger.error("Failed to initialize AWS S3 client: %s", e)
            raise S3ConfigError(f"AWS S3 initialization failed: {e}")

    def generate_canonical_key(self, folder: str, doc_uuid: str, filename: str) -> str:
        """Generate canonical key partitioned by date: e.g. documents/YYYY/MM/<uuid>/original.pdf"""
        now = datetime.now(timezone.utc)
        year_month = now.strftime("%Y/%m")
        return f"{folder}/{year_month}/{doc_uuid}/{filename}"


    def upload_file(
        self,
        file_path_or_bytes: Union[str, Path, bytes, BinaryIO],
        s3_key: str,
        content_type: str = "application/octet-stream",
    ) -> dict:
        """Upload file to S3 if enabled, or save to local storage dir as fallback."""
        if self.enabled and self._s3_client:
            try:
                extra_args = {"ContentType": content_type}
                if isinstance(file_path_or_bytes, (str, Path)):
                    self._s3_client.upload_file(
                        str(file_path_or_bytes),
                        self.bucket,
                        s3_key,
                        ExtraArgs=extra_args,
                    )
                    size = os.path.getsize(str(file_path_or_bytes))
                elif isinstance(file_path_or_bytes, bytes):
                    self._s3_client.put_object(
                        Bucket=self.bucket,
                        Key=s3_key,
                        Body=file_path_or_bytes,
                        ContentType=content_type,
                    )
                    size = len(file_path_or_bytes)
                else:
                    self._s3_client.upload_fileobj(
                        file_path_or_bytes,
                        self.bucket,
                        s3_key,
                        ExtraArgs=extra_args,
                    )
                    size = 0

                logger.info("Uploaded object to S3: s3://%s/%s (bytes=%d)", self.bucket, s3_key, size)
                return {
                    "storage_provider": "S3",
                    "s3_bucket": self.bucket,
                    "s3_key": s3_key,
                    "s3_url": f"s3://{self.bucket}/{s3_key}",
                    "file_size_bytes": size,
                }
            except Exception as e:
                logger.error("Failed to upload to S3 (key=%s): %s", s3_key, e)
                raise S3UploadError(f"S3 upload failed for key '{s3_key}': {e}")
        else:
            # Fallback Local Storage Mode
            dest_path = self.local_dir / s3_key
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(file_path_or_bytes, (str, Path)):
                shutil.copy2(str(file_path_or_bytes), dest_path)
                size = dest_path.stat().st_size
            elif isinstance(file_path_or_bytes, bytes):
                dest_path.write_bytes(file_path_or_bytes)
                size = len(file_path_or_bytes)
            else:
                with open(dest_path, "wb") as f:
                    shutil.copyfileobj(file_path_or_bytes, f)
                size = dest_path.stat().st_size

            logger.info("Saved file locally at %s (bytes=%d)", dest_path, size)
            return {
                "storage_provider": "LOCAL",
                "s3_bucket": None,
                "s3_key": s3_key,
                "s3_url": str(dest_path),
                "file_size_bytes": size,
            }

    def download_file(self, s3_key: str, dest_path: Path) -> Path:
        """Download file from S3 or copy from local fallback storage."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if self.enabled and self._s3_client:
            try:
                self._s3_client.download_file(self.bucket, s3_key, str(dest_path))
                logger.info("Downloaded S3 object s3://%s/%s to %s", self.bucket, s3_key, dest_path)
                return dest_path
            except Exception as e:
                logger.error("Failed to download S3 key %s: %s", s3_key, e)
                raise S3DownloadError(f"S3 download failed for key '{s3_key}': {e}")
        else:
            local_src = self.local_dir / s3_key
            if not local_src.exists():
                raise S3DownloadError(f"Local storage file not found at '{local_src}'")
            shutil.copy2(str(local_src), str(dest_path))
            return dest_path

    def generate_presigned_url(self, s3_key: str, expires_in: Optional[int] = None) -> str:
        """Generate presigned download URL if S3 is active; otherwise return local path/API reference."""
        expires = expires_in or settings.S3_PRESIGNED_EXPIRATION_SECONDS
        if self.enabled and self._s3_client:
            try:
                url = self._s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": s3_key},
                    ExpiresIn=expires,
                )
                return url
            except Exception as e:
                logger.error("Failed to generate presigned URL for key %s: %s", s3_key, e)
                raise S3DownloadError(f"Could not generate presigned URL for key '{s3_key}': {e}")
        else:
            return f"/api/v1/storage/local/{s3_key}"


s3_service = S3Service()
