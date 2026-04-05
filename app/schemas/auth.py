"""
Authentication-related Pydantic schemas.
"""

from uuid import UUID

from app.schemas.base import CamelModel


class RegisterRequest(CamelModel):
    """POST /api/v1/auth/register request body."""

    email: str
    password: str
    password_confirm: str
    name: str


class LoginRequest(CamelModel):
    """POST /api/v1/auth/login request body."""

    email: str
    password: str


class RefreshRequest(CamelModel):
    """POST /api/v1/auth/refresh request body."""

    refresh_token: str


class TokenResponse(CamelModel):
    """Token pair returned on login / register / refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(CamelModel):
    """Public user info returned by GET /api/v1/auth/me."""

    id: UUID
    email: str
    name: str
    default_forecast_period: int = 3
    default_confidence_level: str = "95"
    holiday_calendar: str = "PH"

    model_config = {"from_attributes": True}
