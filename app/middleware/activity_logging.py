"""
Activity Logging Middleware — automatic request-level logging.

Logs every authenticated API request as a background task after
the response is sent. Adds zero latency to API responses.

NOTE: Implemented as a pure ASGI middleware (not BaseHTTPMiddleware)
to avoid the well-known Starlette bug where BaseHTTPMiddleware swallows
AppExceptions before FastAPI's exception handlers can process them,
causing all application errors to appear as 500 INTERNAL_ERROR.
"""

import time

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.activity_logger import log_activity

# Paths that should not be logged
SKIP_PATHS = {"/api/v1/health", "/docs", "/openapi.json", "/redoc"}


class ActivityLoggingMiddleware:
    """Pure ASGI middleware for request activity logging."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        if request.url.path in SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        status_code = 500  # default if something goes wrong

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        # Let the app handle the request normally — exceptions propagate correctly
        await self.app(scope, receive, send_wrapper)

        duration_ms = int((time.time() - start_time) * 1000)
        user_id = getattr(request.state, "user_id", None)

        # Fire-and-forget: log activity after response is sent (non-blocking)
        import asyncio
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            log_activity,
            user_id,
            f"request.{request.method.lower()}",
            {"path": request.url.path, "query": str(request.query_params) or None},
            request.client.host if request.client else None,
            request.headers.get("user-agent", "")[:500],
            duration_ms,
            status_code,
        )
