from fastapi import APIRouter
from app.core.config import settings
from app.db.database import db
from app.workers.worker import worker

router = APIRouter(tags=["Health"])


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


@router.get("/health/live")
def liveness():
    """Liveness probe: verifies process is alive."""
    return {"status": "alive"}


@router.get("/health/ready")
def readiness():
    """Readiness probe: non-blocking check of database, storage, and worker."""
    checks = {}
    is_ready = True

    # 1. Database Check
    try:
        with db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            cursor.fetchone()
            cursor.close()
        checks["database"] = "ready"
    except Exception as e:
        checks["database"] = f"error: {e}"
        is_ready = False

    # 2. Worker Check
    checks["worker"] = "running" if worker._running else "stopped"

    # 3. Storage Mode
    checks["storage"] = "s3" if settings.AWS_ENABLED else "local"

    # 4. Vision Provider
    checks["vision_ocr"] = "groq_enabled" if settings.GROQ_ENABLED else "disabled"

    return {
        "status": "ready" if is_ready else "degraded",
        "checks": checks,
    }
