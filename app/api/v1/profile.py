"""
Profile endpoints — /api/v1/profile/*

GET   /              — Get user profile
PATCH /              — Update profile info/preferences
PUT   /password      — Change password
GET   /holidays      — Get holiday calendar setting
PUT   /holidays      — Update holiday calendar country code
GET   /holidays/builtin  — List built-in holidays for user's country
GET   /holidays/custom   — List user's custom holidays
POST  /holidays/custom   — Create a custom holiday
PUT   /holidays/custom/{id} — Update a custom holiday
DELETE /holidays/custom/{id} — Delete a custom holiday
"""

import datetime

import holidays as holidays_lib
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InvalidCredentialsException,
    NotFoundException,
    ValidationException,
    WeakPasswordException,
)
from app.core.security import hash_password, verify_password
from app.database import get_db
from app.dependencies import get_current_user
from app.models.custom_holiday import CustomHoliday
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

# Full display names for each supported country code
COUNTRY_NAMES: dict[str, str] = {
    "AE": "United Arab Emirates",
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "BD": "Bangladesh",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "BR": "Brazil",
    "CA": "Canada",
    "CH": "Switzerland",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colombia",
    "CZ": "Czech Republic",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "EG": "Egypt",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "HK": "Hong Kong",
    "HR": "Croatia",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IT": "Italy",
    "JP": "Japan",
    "KE": "Kenya",
    "KR": "South Korea",
    "LT": "Lithuania",
    "LV": "Latvia",
    "MX": "Mexico",
    "MY": "Malaysia",
    "NG": "Nigeria",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "PE": "Peru",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "RU": "Russia",
    "SA": "Saudi Arabia",
    "SE": "Sweden",
    "SG": "Singapore",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "TH": "Thailand",
    "TR": "Turkey",
    "TW": "Taiwan",
    "UA": "Ukraine",
    "US": "United States",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "ZA": "South Africa",
}


@router.get("/")
async def get_profile(current_user: User = Depends(get_current_user)):
    """Get the current user's profile."""
    return success_response(data={
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
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
        "name",
        "contact_email",
        "mobile_number",
        "business_logo",
        "default_forecast_period",
        "default_confidence_level",
        "holiday_calendar",
    }

    # Accept camelCase keys from the frontend too
    camel_map = {
        "name": "name",
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
    supported = sorted(
        [
            {"code": code, "name": COUNTRY_NAMES.get(code, code)}
            for code in SUPPORTED_COUNTRIES
        ],
        key=lambda c: c["name"],
    )
    return success_response(data={
        "holidayCalendar": current_user.holiday_calendar,
        "supportedCountries": supported,
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


# ── Built-in Holidays ─────────────────────────────────────────


@router.get("/holidays/builtin")
async def get_builtin_holidays(
    year: int = Query(default=None, description="Year to list holidays for (defaults to current year)"),
    current_user: User = Depends(get_current_user),
):
    """List the built-in (country) holidays for the user's holiday calendar."""
    country = current_user.holiday_calendar or "PH"
    if year is None:
        year = datetime.date.today().year

    try:
        country_holidays = holidays_lib.country_holidays(country, years=year)
    except Exception:
        raise ValidationException(f"Unable to load holidays for country '{country}'")

    holiday_list = [
        {"date": d.isoformat(), "name": n}
        for d, n in sorted(country_holidays.items())
    ]
    return success_response(data={
        "country": country,
        "year": year,
        "holidays": holiday_list,
    })


# ── Custom Holidays CRUD ──────────────────────────────────────


def _check_builtin_collision(country: str, date: datetime.date) -> str | None:
    """Return the built-in holiday name if the date collides, else None."""
    try:
        country_holidays = holidays_lib.country_holidays(country, years=date.year)
        return country_holidays.get(date)
    except Exception:
        return None


@router.get("/holidays/custom")
async def list_custom_holidays(
    year: int = Query(default=None, description="Filter by year (optional)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all custom holidays for the current user."""
    query = db.query(CustomHoliday).filter(CustomHoliday.user_id == current_user.id)
    if year is not None:
        from sqlalchemy import extract
        query = query.filter(extract("year", CustomHoliday.date) == year)
    rows = query.order_by(CustomHoliday.date).all()
    return success_response(data=[
        {
            "id": str(h.id),
            "name": h.name,
            "date": h.date.isoformat(),
            "createdAt": h.created_at.isoformat() if h.created_at else None,
            "updatedAt": h.updated_at.isoformat() if h.updated_at else None,
        }
        for h in rows
    ])


@router.post("/holidays/custom", status_code=201)
async def create_custom_holiday(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new custom holiday."""
    name = (body.get("name") or "").strip()
    date_str = body.get("date", "")

    if not name:
        raise ValidationException("name is required")
    if not date_str:
        raise ValidationException("date is required")

    try:
        holiday_date = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        raise ValidationException("date must be a valid ISO date (YYYY-MM-DD)")

    # Check collision with built-in holidays
    country = current_user.holiday_calendar or "PH"
    builtin_name = _check_builtin_collision(country, holiday_date)
    if builtin_name:
        raise ValidationException(
            f"{holiday_date.strftime('%B %d')} is already a built-in holiday: {builtin_name}"
        )

    # Check duplicate date for this user
    existing = (
        db.query(CustomHoliday)
        .filter(CustomHoliday.user_id == current_user.id, CustomHoliday.date == holiday_date)
        .first()
    )
    if existing:
        raise ValidationException(
            f"You already have a custom holiday on {holiday_date.isoformat()}: {existing.name}"
        )

    holiday = CustomHoliday(
        user_id=current_user.id,
        name=name,
        date=holiday_date,
    )
    db.add(holiday)
    db.commit()
    db.refresh(holiday)

    return success_response(
        data={
            "id": str(holiday.id),
            "name": holiday.name,
            "date": holiday.date.isoformat(),
            "createdAt": holiday.created_at.isoformat() if holiday.created_at else None,
        },
        message="Custom holiday created",
    )


@router.put("/holidays/custom/{holiday_id}")
async def update_custom_holiday(
    holiday_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing custom holiday's name or date."""
    holiday = (
        db.query(CustomHoliday)
        .filter(CustomHoliday.id == holiday_id, CustomHoliday.user_id == current_user.id)
        .first()
    )
    if not holiday:
        raise NotFoundException("Custom holiday")

    new_name = body.get("name")
    new_date_str = body.get("date")

    if new_name is not None:
        new_name = new_name.strip()
        if not new_name:
            raise ValidationException("name cannot be empty")
        holiday.name = new_name

    if new_date_str is not None:
        try:
            new_date = datetime.date.fromisoformat(new_date_str)
        except (ValueError, TypeError):
            raise ValidationException("date must be a valid ISO date (YYYY-MM-DD)")

        # Check built-in collision
        country = current_user.holiday_calendar or "PH"
        builtin_name = _check_builtin_collision(country, new_date)
        if builtin_name:
            raise ValidationException(
                f"{new_date.strftime('%B %d')} is already a built-in holiday: {builtin_name}"
            )

        # Check duplicate date (excluding the current record)
        existing = (
            db.query(CustomHoliday)
            .filter(
                CustomHoliday.user_id == current_user.id,
                CustomHoliday.date == new_date,
                CustomHoliday.id != holiday_id,
            )
            .first()
        )
        if existing:
            raise ValidationException(
                f"You already have a custom holiday on {new_date.isoformat()}: {existing.name}"
            )

        holiday.date = new_date

    db.commit()
    db.refresh(holiday)
    return success_response(
        data={
            "id": str(holiday.id),
            "name": holiday.name,
            "date": holiday.date.isoformat(),
            "updatedAt": holiday.updated_at.isoformat() if holiday.updated_at else None,
        },
        message="Custom holiday updated",
    )


@router.delete("/holidays/custom/{holiday_id}")
async def delete_custom_holiday(
    holiday_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a custom holiday."""
    holiday = (
        db.query(CustomHoliday)
        .filter(CustomHoliday.id == holiday_id, CustomHoliday.user_id == current_user.id)
        .first()
    )
    if not holiday:
        raise NotFoundException("Custom holiday")

    db.delete(holiday)
    db.commit()
    return success_response(data=None, message="Custom holiday deleted")

