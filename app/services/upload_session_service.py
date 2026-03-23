"""
Persisted CSV upload sessions (PostgreSQL) — replaces in-memory pending state.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import NotFoundException, ValidationException
from app.models.csv_upload_session import CsvUploadSession


def _now() -> datetime:
    return datetime.now(timezone.utc)


def delete_expired_sessions(db: Session) -> None:
    """Remove expired upload sessions (best-effort cleanup)."""
    db.query(CsvUploadSession).filter(CsvUploadSession.expires_at < _now()).delete(
        synchronize_session=False
    )
    db.commit()


def create_session(db: Session, user_id, filename: str, raw_bytes: bytes) -> CsvUploadSession:
    """Create a new upload session; prune expired rows globally."""
    delete_expired_sessions(db)
    expires_at = _now() + timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS)
    row = CsvUploadSession(
        user_id=user_id,
        filename=filename or "upload.csv",
        raw_bytes=raw_bytes,
        stage="uploaded",
        column_map=None,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def assert_not_expired(row: CsvUploadSession) -> None:
    if row.expires_at < _now():
        raise ValidationException(
            "Upload session has expired. Please upload your CSV again."
        )


def get_session_for_user(db: Session, session_id: UUID, user_id) -> CsvUploadSession:
    row = (
        db.query(CsvUploadSession)
        .filter(CsvUploadSession.id == session_id, CsvUploadSession.user_id == user_id)
        .first()
    )
    if not row:
        raise NotFoundException("Upload session")
    assert_not_expired(row)
    return row


def mark_validated(db: Session, row: CsvUploadSession, column_map: dict) -> None:
    row.column_map = column_map
    row.stage = "validated"
    db.commit()
    db.refresh(row)


def delete_session(db: Session, row: CsvUploadSession) -> None:
    db.delete(row)
    db.commit()
