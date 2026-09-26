"""API key authentication.

Auth is opt-in (`AUTH_ENABLED`, default off) so the service still starts with no
configuration at all. When it is switched on, every protected route requires a
key from `API_KEYS` in the `X-API-Key` header.
"""

import secrets
from typing import Optional

from fastapi import Header, Query

from app.core.config import settings
from app.constants.errors import ErrorCode
from app.core.exceptions import AppException


class UnauthorizedError(AppException):
    def __init__(self, message: str = "A valid API key is required"):
        super().__init__(
            message=message,
            error_code=ErrorCode.UNAUTHORIZED,
            status_code=401,
        )


class AuthMisconfiguredError(AppException):
    def __init__(self) -> None:
        super().__init__(
            message="AUTH_ENABLED is true but no API_KEYS are configured",
            error_code=ErrorCode.SERVICE_UNAVAILABLE,
            status_code=503,
        )


def require_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, description="API key, for links that cannot send a header"),
) -> None:
    """FastAPI dependency guarding a router.

    The header is the normal path. A query parameter is also accepted because a
    download is a plain browser navigation and cannot carry a custom header.

    Fails closed: enabling auth without configuring any key rejects every
    request rather than silently letting them through.
    """
    if not settings.AUTH_ENABLED:
        return

    valid_keys = settings.api_key_set
    if not valid_keys:
        raise AuthMisconfiguredError()

    presented = x_api_key or api_key
    if not presented:
        raise UnauthorizedError("Missing API key")

    # Constant-time comparison so a wrong key cannot be discovered by timing.
    if not any(secrets.compare_digest(presented, key) for key in valid_keys):
        raise UnauthorizedError("Invalid API key")
