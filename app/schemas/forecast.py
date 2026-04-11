"""
Forecast-related Pydantic schemas — request/response models.
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.schemas.base import CamelModel


class ForecastRequest(CamelModel):
    """Request body for POST /api/v1/forecasts."""

    product_id: UUID
    horizon_days: int = 90
    time_granularity: str = "daily"       # daily | weekly | monthly
    enable_tuning: bool = False
    tune_trials: int = 30
    country: Optional[str] = None         # e.g. 'PH', 'US'


class ForecastStatusResponse(CamelModel):
    """Returned immediately from POST /api/v1/forecasts."""

    id: UUID
    status: str                           # processing | completed | failed


class UploadProductSummary(CamelModel):
    """Per-product summary in the upload preview."""

    product_id: str
    product_name: str
    existing_rows: int
    new_rows: int
    is_new: bool
    is_suspicious: bool
    action: str                           # add | replace


class UploadPreviewResponse(CamelModel):
    """Returned from POST /api/v1/upload."""

    products: list[UploadProductSummary]
    has_suspicious: bool
    quality_report: dict                  # raw quality report
    data_health: dict                     # health scorecard


class UploadValidateRequest(CamelModel):
    """Request body for POST /api/v1/upload/validate."""

    upload_session_id: UUID
    column_map: dict[str, Any]


class UploadConfirmRequest(CamelModel):
    """Request body for POST /api/v1/upload/confirm."""

    upload_session_id: UUID
    skip_product_ids: list[str] = Field(default_factory=list)


class ChatHistoryMessage(CamelModel):
    """A single message in the chat history."""

    role: str                                 # 'user' | 'assistant'
    content: str


class ChatRequest(CamelModel):
    """Request body for POST /api/v1/forecasts/{id}/chat."""

    message: str
    history: list[ChatHistoryMessage] = Field(default_factory=list)
