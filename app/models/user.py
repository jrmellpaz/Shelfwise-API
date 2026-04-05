"""
User SQLAlchemy model — Section 4.2 'users' table.
"""

import uuid

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    contact_email = Column(String, nullable=True)
    mobile_number = Column(String, nullable=True)
    business_logo = Column(Text, nullable=True)
    default_forecast_period = Column(Integer, default=3)       # months (1–12)
    default_confidence_level = Column(String, default="95")     # '80', '95', or 'both'
    holiday_calendar = Column(String, default="PH")             # country code
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    products = relationship(
        "Product", back_populates="user", cascade="all, delete-orphan"
    )
    sales_data = relationship(
        "SalesData", back_populates="user", cascade="all, delete-orphan"
    )
    forecasts = relationship(
        "Forecast", back_populates="user", cascade="all, delete-orphan"
    )
