from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])


@router.get("/local/{s3_key:path}")
def get_local_object(s3_key: str):
    """Serve an object from local storage.

    When AWS is disabled, `S3Service.generate_presigned_url` hands out
    `/api/v1/storage/local/<key>`. Without this route that URL is a dead link.
    """
    root = Path(settings.LOCAL_STORAGE_DIR).resolve()
    target = (root / s3_key).resolve()

    # Reject anything that escapes the storage root (e.g. "../../etc/passwd").
    if not target.is_relative_to(root):
        raise HTTPException(status_code=403, detail="Path outside storage root")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="Object not found in local storage")

    return FileResponse(path=str(target), filename=target.name)
