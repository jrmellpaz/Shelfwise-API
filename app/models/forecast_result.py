"""
ForecastResult SQLAlchemy model — Section 4.2 'forecast_results' table.

Stores individual forecast data points (potentially thousands per forecast).
Separated from the forecasts table for query performance.
"""

import uuid

from sqlalchemy import Column, Date, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ForecastResult(Base):
    __tablename__ = "forecast_results"
    __table_args__ = (
        Index("idx_forecast_results_forecast_id", "forecast_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    forecast_id = Column(
        UUID(as_uuid=True),
        ForeignKey("forecasts.id", ondelete="CASCADE"),
        nullable=False,
    )

    date = Column(Date, nullable=False)
    predicted_value = Column(Float, nullable=False)          # yhat
    lower_bound_80 = Column(Float, nullable=True)            # yhat_lower (80%)
    upper_bound_80 = Column(Float, nullable=True)            # yhat_upper (80%)
    lower_bound_95 = Column(Float, nullable=True)            # yhat_lower (95%)
    upper_bound_95 = Column(Float, nullable=True)            # yhat_upper (95%)
    trend = Column(Float, nullable=True)                     # Trend component
    weekly_seasonality = Column(Float, nullable=True)        # Weekly effect
    yearly_seasonality = Column(Float, nullable=True)        # Yearly effect

    # Relationship
    forecast = relationship("Forecast", back_populates="results")
