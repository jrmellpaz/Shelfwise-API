"""
Activity Logger — non-blocking background task for logging user actions.

Designed to be called via FastAPI BackgroundTasks. Opens its own
database session so it is fully independent of the request lifecycle.
Never raises — errors are silently caught to prevent logging from
crashing the application.
"""

import logging
from uuid import UUID

from app.database import SessionLocal
from app.models.activity_log import ActivityLog

logger = logging.getLogger(__name__)


def log_activity(
    user_id: UUID | None,
    action: str,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    duration_ms: int | None = None,
    status_code: int | None = None,
) -> None:
    """Write an activity log entry to the database.

    This function opens its own session and commits independently.
    It never raises — errors are silently caught to avoid crashing
    the application over a failed log write.
    """
    try:
        db = SessionLocal()
        try:
            entry = ActivityLog(
                user_id=user_id,
                action=action,
                details=details or {},
                ip_address=ip_address,
                user_agent=user_agent,
                duration_ms=duration_ms,
                status_code=status_code,
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception:
        # Logging should never crash the application.
        logger.debug("Failed to write activity log", exc_info=True)
