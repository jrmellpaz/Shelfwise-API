"""
Global exception handlers that convert exceptions to standardized JSON responses.

Registered on the FastAPI app in main.py.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Catch all AppExceptions and return a standardized error response."""
    logger.warning(
        "AppException: %s - %s",
        exc.code,
        exc.message,
        extra={"path": request.url.path, "code": exc.code},
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        },
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch any unhandled exceptions and return a generic 500 error."""
    logger.error(
        "Unhandled exception: %s",
        str(exc),
        extra={"path": request.url.path},
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": [],
            },
        },
    )
