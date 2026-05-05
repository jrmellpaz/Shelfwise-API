"""
Google OAuth2 ID token verification.
"""

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import settings
from app.core.exceptions import AuthenticationException


def verify_google_id_token(token: str) -> dict:
    """Verify a Google ID token and return the decoded payload."""
    try:
        payload = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except ValueError:
        raise AuthenticationException("Invalid Google ID token")

    if not payload.get("email_verified"):
        raise AuthenticationException("Google email not verified")

    return payload
