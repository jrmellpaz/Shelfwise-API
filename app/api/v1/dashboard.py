"""
Dashboard endpoints — /api/v1/dashboard

GET / — Get dashboard stats and recent forecasts
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.forecast import Forecast
from app.models.product import Product
from app.models.sales_data import SalesData
from app.models.user import User
from app.schemas.common import success_response

router = APIRouter()


@router.get("/")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get dashboard stats and recent forecasts."""
    user_id = current_user.id

    # Quick stats
    total_products = (
        db.query(func.count(Product.id))
        .filter(Product.user_id == user_id, Product.is_archived == False)
        .scalar()
    )
    total_forecasts = (
        db.query(func.count(Forecast.id))
        .filter(Forecast.user_id == user_id)
        .scalar()
    )
    avg_mape = (
        db.query(func.avg(Forecast.mape))
        .filter(Forecast.user_id == user_id, Forecast.mape.isnot(None))
        .scalar()
    )
    last_upload_date = (
        db.query(func.max(SalesData.created_at))
        .filter(SalesData.user_id == user_id)
        .scalar()
    )

    # Recent forecasts (last 5)
    recent_forecasts = (
        db.query(Forecast)
        .filter(Forecast.user_id == user_id)
        .order_by(Forecast.forecast_date.desc())
        .limit(5)
        .all()
    )

    return success_response(data={
        "quickStats": {
            "totalProducts": total_products or 0,
            "totalForecasts": total_forecasts or 0,
            "averageMape": round(float(avg_mape), 2) if avg_mape else None,
            "lastUploadDate": last_upload_date.isoformat() if last_upload_date else None,
        },
        "recentForecasts": [
            {
                "id": str(f.id),
                "productId": str(f.product_id),
                "forecastDate": f.forecast_date.isoformat() if f.forecast_date else None,
                "mape": f.mape,
                "selectedModel": f.selected_model,
                "status": f.status,
            }
            for f in recent_forecasts
        ],
    })
