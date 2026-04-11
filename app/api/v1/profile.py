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
GET   /location           — Get user's weather location
PUT   /location           — Set user's weather location
DELETE /location          — Reset location to country capital default
GET   /location/search    — Search cities (geocoding proxy)
GET   /weather            — Get recent weather for user's location
"""

import datetime
import logging

import holidays as holidays_lib
import requests as http_requests
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

# Capital city coordinates for each supported country code.
# Used as default weather location when no custom location is set.
COUNTRY_CAPITALS: dict[str, tuple[str, float, float]] = {
    "AE": ("Abu Dhabi", 24.4539, 54.3773),
    "AR": ("Buenos Aires", -34.6037, -58.3816),
    "AT": ("Vienna", 48.2082, 16.3738),
    "AU": ("Canberra", -35.2809, 149.1300),
    "BD": ("Dhaka", 23.8103, 90.4125),
    "BE": ("Brussels", 50.8503, 4.3517),
    "BG": ("Sofia", 42.6977, 23.3219),
    "BR": ("Brasília", -15.7975, -47.8919),
    "CA": ("Ottawa", 45.4215, -75.6972),
    "CH": ("Bern", 46.9480, 7.4474),
    "CL": ("Santiago", -33.4489, -70.6693),
    "CN": ("Beijing", 39.9042, 116.4074),
    "CO": ("Bogotá", 4.7110, -74.0721),
    "CZ": ("Prague", 50.0755, 14.4378),
    "DE": ("Berlin", 52.5200, 13.4050),
    "DK": ("Copenhagen", 55.6761, 12.5683),
    "EE": ("Tallinn", 59.4370, 24.7536),
    "EG": ("Cairo", 30.0444, 31.2357),
    "ES": ("Madrid", 40.4168, -3.7038),
    "FI": ("Helsinki", 60.1699, 24.9384),
    "FR": ("Paris", 48.8566, 2.3522),
    "GB": ("London", 51.5074, -0.1278),
    "HK": ("Hong Kong", 22.3193, 114.1694),
    "HR": ("Zagreb", 45.8150, 15.9819),
    "HU": ("Budapest", 47.4979, 19.0402),
    "ID": ("Jakarta", -6.2088, 106.8456),
    "IE": ("Dublin", 53.3498, -6.2603),
    "IL": ("Jerusalem", 31.7683, 35.2137),
    "IN": ("New Delhi", 28.6139, 77.2090),
    "IT": ("Rome", 41.9028, 12.4964),
    "JP": ("Tokyo", 35.6762, 139.6503),
    "KE": ("Nairobi", -1.2921, 36.8219),
    "KR": ("Seoul", 37.5665, 126.9780),
    "LT": ("Vilnius", 54.6872, 25.2797),
    "LV": ("Riga", 56.9496, 24.1052),
    "MX": ("Mexico City", 19.4326, -99.1332),
    "MY": ("Kuala Lumpur", 3.1390, 101.6869),
    "NG": ("Abuja", 9.0579, 7.4951),
    "NL": ("Amsterdam", 52.3676, 4.9041),
    "NO": ("Oslo", 59.9139, 10.7522),
    "NZ": ("Wellington", -41.2865, 174.7762),
    "PE": ("Lima", -12.0464, -77.0428),
    "PH": ("Manila", 14.5995, 120.9842),
    "PK": ("Islamabad", 33.6844, 73.0479),
    "PL": ("Warsaw", 52.2297, 21.0122),
    "PT": ("Lisbon", 38.7223, -9.1393),
    "RO": ("Bucharest", 44.4268, 26.1025),
    "RU": ("Moscow", 55.7558, 37.6173),
    "SA": ("Riyadh", 24.7136, 46.6753),
    "SE": ("Stockholm", 59.3293, 18.0686),
    "SG": ("Singapore", 1.3521, 103.8198),
    "SI": ("Ljubljana", 46.0569, 14.5058),
    "SK": ("Bratislava", 48.1486, 17.1077),
    "TH": ("Bangkok", 13.7563, 100.5018),
    "TR": ("Ankara", 39.9334, 32.8597),
    "TW": ("Taipei", 25.0330, 121.5654),
    "UA": ("Kyiv", 50.4501, 30.5234),
    "US": ("Washington, D.C.", 38.8951, -77.0364),
    "VE": ("Caracas", 10.4806, -66.9036),
    "VN": ("Hanoi", 21.0278, 105.8342),
    "ZA": ("Pretoria", -25.7479, 28.2293),
}

logger = logging.getLogger(__name__)


def _resolve_location(user: User) -> dict:
    """Return the user's location, falling back to the capital of their holiday calendar country."""
    country_code = user.holiday_calendar or "PH"
    weather_on = user.weather_enabled if user.weather_enabled is not None else True
    if user.location_latitude is not None and user.location_longitude is not None:
        return {
            "latitude": user.location_latitude,
            "longitude": user.location_longitude,
            "city": user.location_city,
            "countryName": user.location_country_name or COUNTRY_NAMES.get(country_code),
            "countryCode": country_code,
            "isDefault": False,
            "weatherEnabled": weather_on,
        }
    capital = COUNTRY_CAPITALS.get(country_code, COUNTRY_CAPITALS["PH"])
    return {
        "latitude": capital[1],
        "longitude": capital[2],
        "city": capital[0],
        "countryName": COUNTRY_NAMES.get(country_code, country_code),
        "countryCode": country_code,
        "isDefault": True,
        "weatherEnabled": weather_on,
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
        "holidayCalendar": current_user.holiday_calendar,
        "hasGeminiKey": bool(current_user.gemini_api_key),
        "location": _resolve_location(current_user),
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
        "holiday_calendar",
    }

    # Accept camelCase keys from the frontend too
    camel_map = {
        "name": "name",
        "contactEmail": "contact_email",
        "mobileNumber": "mobile_number",
        "businessLogo": "business_logo",
        "defaultForecastPeriod": "default_forecast_period",
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
    """Update the user's holiday calendar country code.

    If the user has no custom location set, automatically updates the
    default location to the capital of the newly selected country.
    """
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
        data={
            "holidayCalendar": current_user.holiday_calendar,
            "location": _resolve_location(current_user),
        },
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


# ── Gemini API Key Management ─────────────────────────────────


def _mask_api_key(key: str) -> str:
    """Return a masked preview of an API key (e.g. 'AIza...xOQU')."""
    if len(key) <= 8:
        return key[:2] + "..." + key[-2:]
    return key[:4] + "..." + key[-4:]


@router.get("/gemini-key")
async def get_gemini_key(
    current_user: User = Depends(get_current_user),
):
    """Check if the user has a custom Gemini API key configured.

    Returns a masked preview of the key and the timestamp when it was set.
    Never returns the full key.
    """
    if not current_user.gemini_api_key:
        return success_response(data={
            "hasKey": False,
            "keyPreview": None,
            "addedAt": None,
        })

    from app.core.encryption import decrypt_value

    decrypted = decrypt_value(current_user.gemini_api_key)
    preview = _mask_api_key(decrypted) if decrypted else "(unable to decrypt)"

    return success_response(data={
        "hasKey": True,
        "keyPreview": preview,
        "addedAt": (
            current_user.gemini_api_key_added_at.isoformat()
            if current_user.gemini_api_key_added_at
            else None
        ),
    })


@router.put("/gemini-key")
async def set_gemini_key(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add or replace the user's custom Gemini API key.

    Validates the key by making a lightweight Gemini API call before storing.
    The key is encrypted at rest using Fernet.
    """
    api_key = (body.get("apiKey") or body.get("api_key") or "").strip()

    if not api_key:
        raise ValidationException("apiKey is required")

    if len(api_key) < 10:
        raise ValidationException("API key appears too short to be valid")

    # Validate the key by making a test call to Gemini
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        # List models is a lightweight call that validates the key
        list(client.models.list())
    except ImportError:
        raise ValidationException("google-genai package is not installed on the server")
    except Exception as e:
        error_msg = str(e).lower()
        if "api key" in error_msg or "invalid" in error_msg or "403" in error_msg or "401" in error_msg:
            raise ValidationException(
                "The API key is invalid. Please check your key and try again."
            )
        raise ValidationException(f"Failed to validate API key: {str(e)}")

    # Encrypt and store
    from app.core.encryption import encrypt_value

    current_user.gemini_api_key = encrypt_value(api_key)
    current_user.gemini_api_key_added_at = datetime.datetime.now(
        datetime.timezone.utc
    )
    db.commit()
    db.refresh(current_user)

    return success_response(
        data={
            "hasKey": True,
            "keyPreview": _mask_api_key(api_key),
            "addedAt": current_user.gemini_api_key_added_at.isoformat(),
        },
        message="Gemini API key saved successfully",
    )


@router.delete("/gemini-key")
async def delete_gemini_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove the user's custom Gemini API key.

    After deletion, Gemini features will fall back to the server's
    default API key (if configured).
    """
    if not current_user.gemini_api_key:
        raise NotFoundException("Gemini API key")

    current_user.gemini_api_key = None
    current_user.gemini_api_key_added_at = None
    db.commit()

    return success_response(data=None, message="Gemini API key removed")


# ── Location Management ───────────────────────────────────────


@router.get("/location")
async def get_location(current_user: User = Depends(get_current_user)):
    """Get the user's weather location.

    Returns the user's custom location if set, otherwise falls back
    to the capital city of their holiday calendar country.
    """
    return success_response(data=_resolve_location(current_user))


@router.put("/location")
async def set_location(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set or update the user's weather location.

    Accepts latitude, longitude, and optional city/country name.
    Used for fetching weather data as forecasting regressors.
    """
    latitude = body.get("latitude")
    longitude = body.get("longitude")

    if latitude is None or longitude is None:
        raise ValidationException("latitude and longitude are required")

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (ValueError, TypeError):
        raise ValidationException("latitude and longitude must be numbers")

    if not (-90 <= latitude <= 90):
        raise ValidationException("latitude must be between -90 and 90")
    if not (-180 <= longitude <= 180):
        raise ValidationException("longitude must be between -180 and 180")

    current_user.location_latitude = latitude
    current_user.location_longitude = longitude
    current_user.location_city = (body.get("city") or "").strip() or None
    current_user.location_country_name = (
        (body.get("countryName") or body.get("country_name") or "").strip() or None
    )

    # Weather toggle (optional — only update if explicitly provided)
    weather_enabled = body.get("weatherEnabled")
    if weather_enabled is not None:
        current_user.weather_enabled = bool(weather_enabled)

    db.commit()
    db.refresh(current_user)
    return success_response(
        data=_resolve_location(current_user),
        message="Location updated",
    )


@router.delete("/location")
async def reset_location(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset the user's location to the default capital city."""
    current_user.location_latitude = None
    current_user.location_longitude = None
    current_user.location_city = None
    current_user.location_country_name = None
    db.commit()
    db.refresh(current_user)
    return success_response(
        data=_resolve_location(current_user),
        message="Location reset to default",
    )


@router.get("/location/search")
async def search_location(
    query: str = Query(..., min_length=2, description="City name to search for"),
    count: int = Query(default=5, ge=1, le=10, description="Max results"),
    current_user: User = Depends(get_current_user),
):
    """Search for cities using the Open-Meteo Geocoding API.

    Returns matching cities with coordinates, useful for the frontend
    city-search autocomplete when setting a weather location.
    """
    try:
        response = http_requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": query.strip(),
                "count": count,
                "language": "en",
                "format": "json",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.warning("Geocoding search failed: %s", e)
        return success_response(data={"results": []})

    raw_results = data.get("results", [])
    results = [
        {
            "city": r.get("name"),
            "region": r.get("admin1"),
            "countryName": r.get("country"),
            "countryCode": r.get("country_code"),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
            "population": r.get("population"),
        }
        for r in raw_results
    ]
    return success_response(data={"results": results})


# ── Weather ───────────────────────────────────────────────────


@router.get("/weather")
async def get_weather(
    days: int = Query(default=7, ge=1, le=90, description="Number of historical days"),
    current_user: User = Depends(get_current_user),
):
    """Fetch recent weather data for the user's location.

    Uses the Open-Meteo Archive API to retrieve daily temperature
    and precipitation data. The location is resolved from the user's
    custom setting or their holiday calendar country's capital.
    """
    location = _resolve_location(current_user)
    lat = location["latitude"]
    lng = location["longitude"]

    end_date = datetime.date.today() - datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=days - 1)

    try:
        response = http_requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "daily": ["temperature_2m_mean", "precipitation_sum"],
                "timezone": "auto",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.warning("Weather fetch failed: %s", e)
        return success_response(data={
            "location": {
                "latitude": lat,
                "longitude": lng,
                "city": location.get("city"),
            },
            "daily": [],
            "error": "Weather data temporarily unavailable",
        })

    daily_data = []
    times = data.get("daily", {}).get("time", [])
    temps = data.get("daily", {}).get("temperature_2m_mean", [])
    precips = data.get("daily", {}).get("precipitation_sum", [])

    for i, date_str in enumerate(times):
        daily_data.append({
            "date": date_str,
            "temperatureMean": temps[i] if i < len(temps) else None,
            "precipitationSum": precips[i] if i < len(precips) else None,
        })

    return success_response(data={
        "location": {
            "latitude": lat,
            "longitude": lng,
            "city": location.get("city"),
        },
        "daily": daily_data,
    })
