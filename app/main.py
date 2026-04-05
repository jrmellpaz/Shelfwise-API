"""
Shelfwise Inventory Forecasting API — Application Entry Point.

Ties together middleware, routers, error handlers, and CORS.
"""

import warnings

# Suppress harmless Pydantic warnings on Python 3.14 where alias_generator
# produces aliases identical to the field name (e.g. single-word fields).
warnings.filterwarnings("ignore", category=UserWarning, module=r"pydantic\._internal")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1.router import v1_router
from app.config import settings
import app.models  # noqa: F401  — ensure all models are registered before queries
from app.core.exceptions import AppException
from app.core.logging import setup_logging
from app.middleware.activity_logging import ActivityLoggingMiddleware
from app.middleware.error_handler import (
    app_exception_handler,
    unhandled_exception_handler,
)

# ── Logging ───────────────────────────────────────────────────
setup_logging(debug=settings.DEBUG)

# ── App Initialization ────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Rate Limiter ──────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# ── Middleware ────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ActivityLoggingMiddleware)

# ── Error Handlers ────────────────────────────────────────────
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# ── Routers ───────────────────────────────────────────────────
app.include_router(v1_router)
