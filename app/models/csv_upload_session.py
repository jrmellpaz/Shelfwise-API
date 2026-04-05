"""
CSV upload session — persisted pending upload state (multi-worker safe).
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class CsvUploadSession(Base):
    __tablename__ = "csv_upload_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(String, nullable=False)
    raw_bytes = Column(LargeBinary, nullable=False)
    status = Column(String(20), nullable=False, default="uploaded")  # uploaded | validated | confirmed | expired
    column_map = Column(JSONB, nullable=True)
    columns_detected = Column(JSONB, nullable=True)
    suggested_mapping = Column(JSONB, nullable=True)
    confidence = Column(JSONB, nullable=True)
    validation_result = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
