"""
API v1 router — aggregates all sub-routers under /api/v1/.

Mounted on the main FastAPI app in main.py.
"""

from fastapi import APIRouter

from app.api.v1 import auth, chatbot, dashboard, forecasts, health, products, profile, shared, upload

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
v1_router.include_router(upload.router, prefix="/upload", tags=["Upload"])
v1_router.include_router(products.router, prefix="/products", tags=["Products"])
v1_router.include_router(forecasts.router, prefix="/forecasts", tags=["Forecasts"])
v1_router.include_router(chatbot.router, prefix="/forecasts", tags=["Chatbot"])
v1_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
v1_router.include_router(profile.router, prefix="/profile", tags=["Profile"])
v1_router.include_router(shared.router, prefix="/shared", tags=["Shared"])
v1_router.include_router(health.router, tags=["System"])
