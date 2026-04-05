"""
CustomHoliday SQLAlchemy model — user-defined holidays.

Each row represents a single custom holiday date for a specific user.
Used alongside the built-in country holidays in Prophet forecasting.
"""

import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class CustomHoliday(Base):
    __tablename__ = "custom_holidays"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_custom_holidays_user_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    user = relationship("User", backref="custom_holidays")
