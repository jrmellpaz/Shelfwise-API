"""
SalesData SQLAlchemy model — Section 4.2 'sales_data' table.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class SalesData(Base):
    __tablename__ = "sales_data"
    __table_args__ = (
        CheckConstraint("quantity_sold > 0", name="ck_sales_data_qty_positive"),
        # Composite indexes for multi-user query performance
        Index("idx_sales_data_user_product", "user_id", "product_id"),
        Index("idx_sales_data_user_date", "user_id", "date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date = Column(Date, nullable=False, index=True)
    quantity_sold = Column(Numeric, nullable=False)
    upload_id = Column(UUID(as_uuid=True), nullable=True)  # Groups rows from same upload
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="sales_data")
    product = relationship("Product", back_populates="sales_data")
