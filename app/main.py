import contextlib
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.exceptions import AppException
from app.core.security import require_api_key
from app.constants.errors import ErrorCode
from app.schemas.common import ApiErrorResponse, ErrorDetail
from app.db.migrations import run_migrations
from app.workers.worker import worker

from app.api.routes.health import router as health_router
from app.api.routes.documents import router as documents_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.settings import router as settings_router
from app.api.routes.storage import router as storage_router

logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # --- Startup ---
    setup_logging()
    logger.info("Initializing application: %s (%s)", settings.APP_NAME, settings.APP_ENV)
    settings.ensure_directories()
    run_migrations()

    if settings.WORKER_ENABLED:
        worker.start()
        worker.install_signal_handlers()

    yield

    # --- Shutdown ---
    logger.info("Shutting down application...")
    if settings.WORKER_ENABLED:
        worker.stop()
    logger.info("Application shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Production-grade PDF processing and text extraction service",
    lifespan=lifespan,
)

# CORS Middleware.
# "*" with allow_credentials=True is rejected outright by browsers, so
# credentials are only enabled when an explicit origin list is configured.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
)


# Correlation ID Middleware
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:10]}"
    request.state.request_id = request_id
    start_time = time.time()

    response = await call_next(request)

    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"
    return response


# Application Exception Handler
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "Application error [%s]: %s (status=%d, req_id=%s)",
        exc.error_code,
        exc.message,
        exc.status_code,
        request_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiErrorResponse(
            success=False,
            error=ErrorDetail(
                code=exc.error_code.value,
                message=exc.message,
                request_id=request_id,
                details=exc.details,
            ),
        ).model_dump(),
    )


# Request Validation Exception Handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)
    logger.warning("Validation error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ApiErrorResponse(
            success=False,
            error=ErrorDetail(
                code=ErrorCode.VALIDATION_ERROR.value,
                message="Request input validation failed",
                request_id=request_id,
                details={"errors": exc.errors()},
            ),
        ).model_dump(),
    )


# Global Unhandled Exception Handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error("Unhandled server exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ApiErrorResponse(
            success=False,
            error=ErrorDetail(
                code=ErrorCode.INTERNAL_SERVER_ERROR.value,
                message="An internal server error occurred",
                request_id=request_id,
            ),
        ).model_dump(),
    )


# Include Routers
# Health stays open so liveness/readiness probes work without credentials.
app.include_router(health_router)

# Everything touching documents or configuration is guarded. The dependency is
# a no-op while AUTH_ENABLED is false.
_protected = [Depends(require_api_key)]
app.include_router(documents_router, dependencies=_protected)
app.include_router(jobs_router, dependencies=_protected)
app.include_router(settings_router, dependencies=_protected)
app.include_router(storage_router, dependencies=_protected)

# Web UI — mounted last so every API route above keeps precedence over the
# catch-all static mount. html=True serves index.html for "/".
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")
else:
    logger.warning("Static UI directory not found at %s; serving API only", STATIC_DIR)
