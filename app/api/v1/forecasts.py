"""
Forecast endpoints — /api/v1/forecasts/*

POST /                   — Generate a new forecast (async)
GET  /                   — List forecast history (paginated)
GET  /{id}               — Get full forecast details
GET  /{id}/results       — Get forecast data points
GET  /{id}/components    — Get component breakdown
GET  /{id}/export/csv    — Download forecast results as CSV
GET  /{id}/export/chart  — Download forecast chart as PNG
GET  /{id}/export/pdf    — Download forecast report as PDF
POST /{id}/share         — Generate a shareable link
DELETE /{id}/share       — Revoke a shareable link
"""

import calendar
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.dependencies import get_current_user
from app.models.forecast import Forecast
from app.models.product import Product
from app.models.user import User
from app.core.exceptions import NotFoundException, ValidationException
from app.schemas.common import success_response, paginated_response
from app.schemas.forecast import ForecastRequest, ForecastStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_forecast_in_background(forecast_id: str):
    """Wrapper that creates its own DB session for the background task."""
    from app.services.forecast_service import run_forecast

    db = SessionLocal()
    try:
        run_forecast(forecast_id, db)
    finally:
        db.close()


@router.post("/")
async def generate_forecast(
    body: ForecastRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a new forecast (async via BackgroundTasks).

    Creates a Forecast record with status='processing', kicks off
    the pipeline in a background task, and returns immediately.
    """
    # Verify product exists and belongs to this user
    product = (
        db.query(Product)
        .filter(Product.id == body.product_id, Product.user_id == current_user.id)
        .first()
    )
    if not product:
        raise NotFoundException("Product")

    # Create forecast record
    forecast = Forecast(
        user_id=current_user.id,
        product_id=product.id,
        forecast_date=datetime.utcnow(),
        forecast_horizon=body.horizon_days,
        time_granularity=body.time_granularity,
        confidence_level=body.confidence_level,
        model_parameters={
            "enable_tuning": body.enable_tuning,
            "tune_trials": body.tune_trials,
        },
        status="processing",
    )
    db.add(forecast)
    db.commit()
    db.refresh(forecast)

    logger.info("Created forecast %s for product %s — starting background task", forecast.id, product.product_id)

    # Kick off background processing
    background_tasks.add_task(_run_forecast_in_background, str(forecast.id))

    return success_response(
        data={"id": str(forecast.id), "status": "processing"},
        message="Forecast generation started",
    )


@router.get("/")
async def list_forecasts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    product_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List forecast history for the current user (paginated)."""
    query = db.query(Forecast).filter(Forecast.user_id == current_user.id)
    if product_id:
        query = query.filter(Forecast.product_id == product_id)

    query = query.order_by(Forecast.forecast_date.desc())
    total_items = query.count()
    forecasts = query.offset((page - 1) * limit).limit(limit).all()

    return paginated_response(
        data=[
            {
                "id": str(f.id),
                "productId": str(f.product_id),
                "forecastDate": f.forecast_date.isoformat() if f.forecast_date else None,
                "forecastHorizon": f.forecast_horizon,
                "selectedModel": f.selected_model,
                "demandProfile": f.demand_profile,
                "mape": f.mape,
                "status": f.status,
            }
            for f in forecasts
        ],
        page=page,
        limit=limit,
        total_items=total_items,
    )


@router.get("/{forecast_uuid}")
async def get_forecast(
    forecast_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full forecast details including metrics and explanation."""
    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")

    return success_response(data={
        "id": str(forecast.id),
        "productId": str(forecast.product_id),
        "forecastDate": forecast.forecast_date.isoformat() if forecast.forecast_date else None,
        "forecastHorizon": forecast.forecast_horizon,
        "timeGranularity": forecast.time_granularity,
        "confidenceLevel": forecast.confidence_level,
        "seasonalityMode": forecast.seasonality_mode,
        "selectedModel": forecast.selected_model,
        "demandProfile": forecast.demand_profile,
        "status": forecast.status,
        "progressStep": forecast.progress_step,
        "progressTotal": forecast.progress_total,
        "progressLabel": forecast.progress_label,
        "mape": forecast.mape,
        "wape": forecast.wape,
        "smape": forecast.smape,
        "mase": forecast.mase,
        "rmse": forecast.rmse,
        "mae": forecast.mae,
        "dataStartDate": forecast.data_start_date.isoformat() if forecast.data_start_date else None,
        "dataEndDate": forecast.data_end_date.isoformat() if forecast.data_end_date else None,
        "dataRowCount": forecast.data_row_count,
        "modelParameters": forecast.model_parameters,
        "tunedParameters": forecast.tuned_parameters,
        "aiExplanation": forecast.ai_explanation,
        "errorMessage": forecast.error_message,
    })


@router.get("/{forecast_uuid}/results")
async def get_forecast_results(
    forecast_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get forecast result data points."""
    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")

    return success_response(data=[
        {
            "date": r.date.isoformat() if r.date else None,
            "predictedValue": r.predicted_value,
            "lowerBound80": r.lower_bound_80,
            "upperBound80": r.upper_bound_80,
            "lowerBound95": r.lower_bound_95,
            "upperBound95": r.upper_bound_95,
            "trend": r.trend,
            "weeklySeasonality": r.weekly_seasonality,
            "yearlySeasonality": r.yearly_seasonality,
        }
        for r in forecast.results
    ])


@router.get("/{forecast_uuid}/components")
async def get_forecast_components(
    forecast_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get component breakdown (trend, weekly seasonality, yearly seasonality)."""
    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")

    # Build trend from results
    trend = []
    weekly_effects: dict[str, list[float]] = {}
    yearly_effects: dict[int, list[float]] = {}

    for r in forecast.results:
        if r.trend is not None:
            trend.append({
                "date": r.date.isoformat() if r.date else None,
                "value": r.trend,
            })

        if r.date:
            # Aggregate weekly seasonality by day name
            if r.weekly_seasonality is not None:
                day_name = r.date.strftime("%A")
                weekly_effects.setdefault(day_name, []).append(r.weekly_seasonality)

            # Aggregate yearly seasonality by month
            if r.yearly_seasonality is not None:
                month_num = r.date.month
                yearly_effects.setdefault(month_num, []).append(r.yearly_seasonality)

    # Average weekly effects
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekly = [
        {"dayOfWeek": day, "effect": round(sum(weekly_effects[day]) / len(weekly_effects[day]), 2)}
        for day in day_order
        if day in weekly_effects
    ]

    # Average yearly effects
    yearly = [
        {"month": calendar.month_name[m], "effect": round(sum(yearly_effects[m]) / len(yearly_effects[m]), 2)}
        for m in sorted(yearly_effects.keys())
    ]

    return success_response(data={
        "trend": trend,
        "weekly": weekly,
        "yearly": yearly,
    })


@router.get("/{forecast_uuid}/export/csv")
async def export_forecast_csv(
    forecast_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export forecast result data points as a downloadable CSV file."""
    from fastapi.responses import StreamingResponse
    from app.services.export_service import generate_csv_export

    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")

    if forecast.status != "completed":
        raise ValidationException(
            f"Forecast is not ready for export (status: {forecast.status})"
        )

    if not forecast.results:
        raise ValidationException("No forecast results available to export")

    buffer = generate_csv_export(forecast.results)

    # Build a descriptive filename
    product = (
        db.query(Product)
        .filter(Product.id == forecast.product_id)
        .first()
    )
    product_label = product.product_id if product else "forecast"
    date_label = forecast.forecast_date.strftime("%Y%m%d") if forecast.forecast_date else "export"
    filename = f"{product_label}_forecast_{date_label}.csv"

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{forecast_uuid}/export/chart")
async def export_forecast_chart(
    forecast_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export forecast chart as a PNG image."""
    from fastapi.responses import StreamingResponse
    from app.services.export_service import generate_chart_png
    from app.models.sales_data import SalesData

    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")
    if forecast.status != "completed":
        raise ValidationException(
            f"Forecast is not ready for export (status: {forecast.status})"
        )
    if not forecast.results:
        raise ValidationException("No forecast results available to export")

    # Load historical data for the chart
    historical = (
        db.query(SalesData)
        .filter(SalesData.product_id == forecast.product_id)
        .order_by(SalesData.date)
        .all()
    )

    buffer = generate_chart_png(forecast, forecast.results, historical)

    product = db.query(Product).filter(Product.id == forecast.product_id).first()
    product_label = product.product_id if product else "forecast"
    date_label = forecast.forecast_date.strftime("%Y%m%d") if forecast.forecast_date else "export"
    filename = f"{product_label}_chart_{date_label}.png"

    return StreamingResponse(
        buffer,
        media_type="image/png",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{forecast_uuid}/export/pdf")
async def export_forecast_pdf(
    forecast_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export forecast report as a PDF document."""
    from fastapi.responses import StreamingResponse
    from app.services.export_service import generate_pdf_report
    from app.models.sales_data import SalesData

    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")
    if forecast.status != "completed":
        raise ValidationException(
            f"Forecast is not ready for export (status: {forecast.status})"
        )
    if not forecast.results:
        raise ValidationException("No forecast results available to export")

    product = db.query(Product).filter(Product.id == forecast.product_id).first()

    # Load historical data for the chart in the report
    historical = (
        db.query(SalesData)
        .filter(SalesData.product_id == forecast.product_id)
        .order_by(SalesData.date)
        .all()
    )

    buffer = generate_pdf_report(
        forecast, product, current_user, forecast.results, historical
    )

    product_label = product.product_id if product else "forecast"
    date_label = forecast.forecast_date.strftime("%Y%m%d") if forecast.forecast_date else "export"
    filename = f"{product_label}_report_{date_label}.pdf"

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Sharing ───────────────────────────────────────────────────


@router.post("/{forecast_uuid}/share")
async def create_share_link(
    forecast_uuid: UUID,
    body: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a shareable public link for a forecast.

    Request body (optional):
        - expires_in_hours: int — hours until the link expires (null/0 = never expires)
    """
    import secrets
    from datetime import timedelta

    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")
    if forecast.status != "completed":
        raise ValidationException(
            f"Only completed forecasts can be shared (status: {forecast.status})"
        )

    # Generate a short, URL-safe token
    if not forecast.share_token:
        forecast.share_token = secrets.token_urlsafe(16)

    # Set expiry (None = never expires)
    body = body or {}
    expires_in_hours = body.get("expires_in_hours") or body.get("expiresInHours")
    if expires_in_hours and int(expires_in_hours) > 0:
        forecast.share_expires_at = datetime.utcnow() + timedelta(hours=int(expires_in_hours))
    else:
        forecast.share_expires_at = None

    db.commit()
    db.refresh(forecast)

    return success_response(
        data={
            "shareToken": forecast.share_token,
            "shareUrl": f"/api/v1/shared/forecasts/{forecast.share_token}",
            "expiresAt": forecast.share_expires_at.isoformat() if forecast.share_expires_at else None,
        },
        message="Share link created",
    )


@router.delete("/{forecast_uuid}/share")
async def revoke_share_link(
    forecast_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke (disable) a forecast's shareable link."""
    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")

    forecast.share_token = None
    forecast.share_expires_at = None
    db.commit()

    return success_response(data=None, message="Share link revoked")

