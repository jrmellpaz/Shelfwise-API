"""
Profile endpoints — /api/v1/profile/*

GET   /          — Get user profile
PATCH /          — Update profile info/preferences
PUT   /password  — Change password
GET   /holidays  — Get holiday calendar
PUT   /holidays  — Update holiday calendar
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InvalidCredentialsException,
    ValidationException,
    WeakPasswordException,
)
from app.core.security import hash_password, verify_password
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.common import success_response

router = APIRouter()

# Prophet-supported country codes for holiday calendars
SUPPORTED_COUNTRIES = {
    "PH", "US", "CA", "GB", "AU", "DE", "FR", "JP", "KR", "SG", "MY",
    "IN", "BR", "MX", "ES", "IT", "NL", "SE", "NO", "DK", "FI", "NZ",
    "IE", "AT", "BE", "CH", "PT", "PL", "CZ", "HU", "RO", "BG", "HR",
    "SK", "SI", "LT", "LV", "EE", "ZA", "NG", "KE", "EG", "AR", "CL",
    "CO", "PE", "VE", "ID", "TH", "VN", "TW", "HK", "CN", "RU", "UA",
    "TR", "SA", "AE", "IL", "PK", "BD",
}


@router.get("/")
async def get_profile(current_user: User = Depends(get_current_user)):
    """Get the current user's profile."""
    return success_response(data={
        "id": str(current_user.id),
        "email": current_user.email,
        "businessName": current_user.business_name,
        "contactEmail": current_user.contact_email,
        "mobileNumber": current_user.mobile_number,
        "businessLogo": current_user.business_logo,
        "defaultForecastPeriod": current_user.default_forecast_period,
        "defaultConfidenceLevel": current_user.default_confidence_level,
        "holidayCalendar": current_user.holiday_calendar,
        "createdAt": current_user.created_at.isoformat() if current_user.created_at else None,
    })


@router.patch("/")
async def update_profile(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update profile info and forecasting preferences."""
    allowed_fields = {
        "business_name",
        "contact_email",
        "mobile_number",
        "business_logo",
        "default_forecast_period",
        "default_confidence_level",
        "holiday_calendar",
    }

    # Accept camelCase keys from the frontend too
    camel_map = {
        "businessName": "business_name",
        "contactEmail": "contact_email",
        "mobileNumber": "mobile_number",
        "businessLogo": "business_logo",
        "defaultForecastPeriod": "default_forecast_period",
        "defaultConfidenceLevel": "default_confidence_level",
        "holidayCalendar": "holiday_calendar",
    }

    for key, value in body.items():
        field = camel_map.get(key, key)
        if field in allowed_fields:
            setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)
    return success_response(data=None, message="Profile updated successfully")


@router.put("/password")
async def change_password(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the user's password (requires current password)."""
    current_password = body.get("currentPassword") or body.get("current_password")
    new_password = body.get("newPassword") or body.get("new_password")

    if not current_password or not new_password:
        raise WeakPasswordException("Current password and new password are required")

    if not verify_password(current_password, current_user.password_hash):
        raise InvalidCredentialsException()

    import re
    if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$", new_password):
        raise WeakPasswordException(
            "Password must be at least 8 characters with 1 uppercase, "
            "1 lowercase, and 1 number"
        )

    current_user.password_hash = hash_password(new_password)
    db.commit()
    return success_response(data=None, message="Password changed successfully")


@router.get("/holidays")
async def get_holidays(current_user: User = Depends(get_current_user)):
    """Get the user's holiday calendar setting."""
    return success_response(data={
        "holidayCalendar": current_user.holiday_calendar,
        "supportedCountries": sorted(SUPPORTED_COUNTRIES),
    })


@router.put("/holidays")
async def update_holidays(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the user's holiday calendar country code."""
    country = body.get("holidayCalendar") or body.get("holiday_calendar")

    if not country:
        raise ValidationException("holidayCalendar is required")

    country = country.upper().strip()
    if country not in SUPPORTED_COUNTRIES:
        raise ValidationException(
            f"Unsupported country code '{country}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_COUNTRIES))}"
        )

    current_user.holiday_calendar = country
    db.commit()
    db.refresh(current_user)
    return success_response(
        data={"holidayCalendar": current_user.holiday_calendar},
        message="Holiday calendar updated",
    )

