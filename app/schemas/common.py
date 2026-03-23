"""
Standardized API response wrappers (Section 7.3.2–7.3.3).

All API responses are wrapped in type-safe Pydantic models using Python Generics.
"""

import math
from typing import Any, Generic, Optional, TypeVar

from app.schemas.base import CamelModel

T = TypeVar("T")


# ── Success Responses ─────────────────────────────────────────


class ApiResponse(CamelModel, Generic[T]):
    """Standard success response wrapper."""

    status: str = "success"
    data: T
    message: Optional[str] = None


class PaginationMeta(CamelModel):
    """Pagination metadata included in paginated responses."""

    page: int
    limit: int
    total_items: int   # JSON alias totalItems when model is serialized
    total_pages: int   # JSON alias totalPages when model is serialized


class PaginatedResponse(CamelModel, Generic[T]):
    """Success response with paginated data."""

    status: str = "success"
    data: list[T]
    pagination: PaginationMeta


# ── Error Responses ───────────────────────────────────────────


class ErrorDetail(CamelModel):
    """Structured error information."""

    code: str              # Machine-readable error code (e.g. "VALIDATION_ERROR")
    message: str           # Human-readable error message
    details: list[Any] = []  # Optional array of specific field errors


class ErrorResponse(CamelModel):
    """Standard error response wrapper."""

    status: str = "error"
    error: ErrorDetail


# ── Utility Functions ─────────────────────────────────────────


def json_safe(obj: Any) -> Any:
    """Recursively convert numpy scalars/arrays so FastAPI can JSON-encode responses."""
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore

    if np is not None:
        if isinstance(obj, np.ndarray):
            return json_safe(obj.tolist())
        if isinstance(obj, np.generic):
            return obj.item()
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(json_safe(v) for v in obj)
    return obj


def success_response(data: Any, message: Optional[str] = None) -> dict:
    """Create a standardized success response dict."""
    response: dict[str, Any] = {"status": "success", "data": data}
    if message:
        response["message"] = message
    return response


def paginated_response(
    data: list,
    page: int,
    limit: int,
    total_items: int,
) -> dict:
    """Create a standardized paginated response dict."""
    return {
        "status": "success",
        "data": data,
        "pagination": {
            "page": page,
            "limit": limit,
            "totalItems": total_items,
            "totalPages": math.ceil(total_items / limit) if limit > 0 else 0,
        },
    }
