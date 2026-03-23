"""
Forecast SQLAlchemy model — Section 4.2 'forecasts' table.
"""

import uuid

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        Index("idx_forecasts_user_product", "user_id", "product_id"),
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

    # Metadata
    forecast_date = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    forecast_horizon = Column(Integer, nullable=False)                  # days
    time_granularity = Column(String, nullable=True)                    # daily/weekly/monthly
    confidence_level = Column(String, nullable=True)                    # '80', '95', 'both'
    seasonality_mode = Column(String, nullable=True)                    # additive/multiplicative
    selected_model = Column(String, nullable=True)                      # prophet, croston_sba, etc.
    demand_profile = Column(String, nullable=True)                      # smooth/erratic/intermittent/lumpy
    status = Column(String, default="processing")                       # processing/generating_explanation/completed/failed

    # Coarse progress for polling UI (e.g. step 2 of 5); cleared when completed/failed
    progress_step = Column(Integer, nullable=True)
    progress_total = Column(Integer, nullable=True)
    progress_label = Column(String(120), nullable=True)

    # Accuracy metrics
    mape = Column(Float, nullable=True)
    wape = Column(Float, nullable=True)
    smape = Column(Float, nullable=True)
    mase = Column(Float, nullable=True)
    rmse = Column(Float, nullable=True)
    mae = Column(Float, nullable=True)

    # Data context
    data_start_date = Column(Date, nullable=True)
    data_end_date = Column(Date, nullable=True)
    data_row_count = Column(Integer, nullable=True)

    # Parameters & explanation
    model_parameters = Column(JSONB, nullable=True)
    tuned_parameters = Column(JSONB, nullable=True)
    ai_explanation = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)         # Set when status = 'failed'

    # Sharing
    share_token = Column(String, unique=True, nullable=True, index=True)
    share_expires_at = Column(DateTime(timezone=True), nullable=True)  # NULL = no expiry

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="forecasts")
    product = relationship("Product", back_populates="forecasts")
    results = relationship(
        "ForecastResult", back_populates="forecast", cascade="all, delete-orphan"
    )
