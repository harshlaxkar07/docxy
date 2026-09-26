from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Standardized application error code")
    message: str = Field(..., description="Human-readable error description")
    request_id: Optional[str] = Field(None, description="Request correlation identifier")
    details: Optional[dict[str, Any]] = Field(default=None, description="Additional context or validation errors")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    error: Optional[ErrorDetail] = None


class ApiErrorResponse(BaseModel):
    success: bool = False
    data: Optional[Any] = None
    error: ErrorDetail
