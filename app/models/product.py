"""
Product SQLAlchemy model — Section 4.2 'products' table.
"""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        # Composite index for fast user-scoped queries
        # Individual index on user_id for FK lookups
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = Column(String, nullable=False)          # CSV product identifier
    name = Column(String, nullable=False)                # From CSV product_name
    category = Column(String, nullable=True)             # User-added metadata
    description = Column(Text, nullable=True)            # User-added metadata
    notes = Column(Text, nullable=True)                  # User-added metadata
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    user = relationship("User", back_populates="products")
    sales_data = relationship(
        "SalesData", back_populates="product", cascade="all, delete-orphan"
    )
    forecasts = relationship(
        "Forecast", back_populates="product", cascade="all, delete-orphan"
    )
