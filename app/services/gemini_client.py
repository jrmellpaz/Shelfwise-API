"""
Shared Gemini client factory — single source of truth for client creation
and API key validation.

Both gemini_service.py and chatbot_service.py use this module instead of
independently creating clients and validating keys.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {"", "your-gemini-api-key-here"}


def is_gemini_available() -> bool:
    """Quick check whether the Gemini API key is configured."""
    api_key = settings.GEMINI_API_KEY
    return bool(api_key) and api_key not in _PLACEHOLDER_KEYS


def get_gemini_client():
    """Create and return a google.genai Client, or None if unavailable.

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
