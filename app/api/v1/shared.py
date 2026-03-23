"""
Shared forecast endpoints — /api/v1/shared/*

Public (no authentication required):

GET  /forecasts/{token}  — View a shared forecast report
"""

import calendar
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.forecast import Forecast
from app.models.product import Product
from app.models.forecast_result import ForecastResult
from app.core.exceptions import NotFoundException
from app.schemas.common import success_response

router = APIRouter()


@router.get("/forecasts/{share_token}")
async def get_shared_forecast(
    share_token: str,
    db: Session = Depends(get_db),
):
    """View a shared forecast report (no authentication required).

    Returns forecast metadata, accuracy metrics, AI explanation,
    product info, and all forecast result data points.
    """
    forecast = (
        db.query(Forecast)
        .filter(Forecast.share_token == share_token)
        .first()
    )
    if not forecast:
        raise NotFoundException("Shared forecast")

    # Check expiry (None = never expires)
    if forecast.share_expires_at:
        now = datetime.now(timezone.utc)
        exp = forecast.share_expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            raise NotFoundException("This share link has expired")

    # Load product info
    product = db.query(Product).filter(Product.id == forecast.product_id).first()

    # Load forecast results
    results = (
        db.query(ForecastResult)
        .filter(ForecastResult.forecast_id == forecast.id)
        .order_by(ForecastResult.date)
        .all()
    )

    # Build result data points
    result_data = []
    for r in results:
        point = {
            "date": r.date.isoformat() if r.date else None,
            "predictedValue": r.predicted_value,
            "lowerBound80": r.lower_bound_80,
            "upperBound80": r.upper_bound_80,
            "lowerBound95": r.lower_bound_95,
            "upperBound95": r.upper_bound_95,
        }
        if r.trend is not None:
            point["trend"] = r.trend
        if r.weekly_seasonality is not None:
            point["weeklySeasonality"] = r.weekly_seasonality
        if r.yearly_seasonality is not None:
            point["yearlySeasonality"] = r.yearly_seasonality
        result_data.append(point)

    # Build the response
    data = {
        "forecast": {
            "id": str(forecast.id),
            "forecastDate": forecast.forecast_date.isoformat() if forecast.forecast_date else None,
            "forecastHorizon": forecast.forecast_horizon,
            "timeGranularity": forecast.time_granularity,
            "confidenceLevel": forecast.confidence_level,
            "selectedModel": forecast.selected_model,
            "demandProfile": forecast.demand_profile,
            "seasonalityMode": forecast.seasonality_mode,
            "status": forecast.status,
            "progressStep": forecast.progress_step,
            "progressTotal": forecast.progress_total,
            "progressLabel": forecast.progress_label,
            "metrics": {
                "mape": forecast.mape,
                "wape": forecast.wape,
                "smape": forecast.smape,
                "mase": forecast.mase,
                "rmse": forecast.rmse,
                "mae": forecast.mae,
            },
            "dataStartDate": forecast.data_start_date.isoformat() if forecast.data_start_date else None,
            "dataEndDate": forecast.data_end_date.isoformat() if forecast.data_end_date else None,
            "dataRowCount": forecast.data_row_count,
            "aiExplanation": forecast.ai_explanation,
        },
        "product": {
            "productId": product.product_id if product else None,
            "name": product.name if product else None,
            "category": product.category if product else None,
        } if product else None,
        "results": result_data,
    }

    return success_response(data=data)
