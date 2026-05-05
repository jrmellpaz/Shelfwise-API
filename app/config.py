"""
Application configuration via Pydantic Settings.

Reads from environment variables and .env file.
Maps the existing .env keys to the settings attributes.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration loaded from environment variables / .env file."""

    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str

    # ── JWT Security ──────────────────────────────────────────
    # .env uses SECRET_KEY / ALGORITHM / ACCESS_TOKEN_EXPIRE_MINUTES
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Google OAuth ──────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""

    # ── Gemini API ────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL_NAME: str = "gemini-3.1-flash-lite-preview"

    # ── AI Explanation ────────────────────────────────────────
    EXPLANATION_TEMPERATURE: float = 0.3

    # ── Chatbot ───────────────────────────────────────────────
    CHATBOT_MAX_HISTORY_MESSAGES: int = 20
    CHATBOT_TEMPERATURE: float = 0.7
    CHATBOT_MAX_OUTPUT_TOKENS: int = 1024

    # ── Upload Limits ─────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 10
    MAX_UPLOAD_ROWS: int = 50_000
    UPLOAD_SESSION_TTL_HOURS: int = 24

    # ── Weather API Defaults ──────────────────────────────────
    DEFAULT_LATITUDE: float = 14.5995
    DEFAULT_LONGITUDE: float = 120.9842

    # ── Application ───────────────────────────────────────────
    APP_NAME: str = "Shelfwise Inventory Forecasting API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }


settings = Settings()
