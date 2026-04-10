"""
Shared Gemini client factory — single source of truth for client creation
and API key validation.

Both gemini_service.py and chatbot_service.py use this module instead of
independently creating clients and validating keys.

Supports per-user API keys (encrypted in DB) with fallback to server default.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {"", "your-gemini-api-key-here"}


def _resolve_api_key(user=None) -> str | None:
    """Return the best available Gemini API key.

    Priority:
    1. User's own key (decrypted from DB) — if present and valid
    2. Server-wide key from settings.GEMINI_API_KEY
    """
    if user is not None:
        encrypted = getattr(user, "gemini_api_key", None)
        if encrypted:
            from app.core.encryption import decrypt_value

            decrypted = decrypt_value(encrypted)
            if decrypted and decrypted not in _PLACEHOLDER_KEYS:
                return decrypted
            logger.warning("User %s has a stored key but decryption failed", user.id)

    # Fallback to server default
    server_key = settings.GEMINI_API_KEY
    if server_key and server_key not in _PLACEHOLDER_KEYS:
        return server_key

    return None


# ── Server-wide helpers (unchanged API) ───────────────────────


def is_gemini_available() -> bool:
    """Quick check whether the server-wide Gemini API key is configured."""
    api_key = settings.GEMINI_API_KEY
    return bool(api_key) and api_key not in _PLACEHOLDER_KEYS


def get_gemini_client():
    """Create and return a google.genai Client using the server key, or None.

    Returns None (instead of raising) when:
    - API key is missing or is a placeholder
    - google-genai package is not installed
    - Client construction fails for any other reason
    """
    if not is_gemini_available():
        logger.info("GEMINI_API_KEY not configured — Gemini unavailable")
        return None

    try:
        from google import genai
    except ImportError:
        logger.warning("google-genai not installed — Gemini unavailable")
        return None

    try:
        return genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception as e:
        logger.error("Failed to create Gemini client: %s", e)
        return None


# ── Per-user helpers ──────────────────────────────────────────


def is_gemini_available_for_user(user=None) -> bool:
    """Check whether Gemini is available for a specific user.

    Returns True if the user has a custom key OR the server default is set.
    """
    return _resolve_api_key(user) is not None


def get_gemini_client_for_user(user=None):
    """Create a google.genai Client using the user's key (or server fallback).

    Returns None when no key is available or client creation fails.
    """
    api_key = _resolve_api_key(user)
    if not api_key:
        logger.info("No Gemini API key available (user=%s)", getattr(user, "id", None))
        return None

    try:
        from google import genai
    except ImportError:
        logger.warning("google-genai not installed — Gemini unavailable")
        return None

    try:
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.error("Failed to create Gemini client: %s", e)
        return None
