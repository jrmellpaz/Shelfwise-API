"""
Import all models so that SQLAlchemy mappers are fully initialized
before any queries are executed. This prevents InvalidRequestError
when relationships reference models by string name (e.g. "User").
"""

from app.models.user import User  # noqa: F401
from app.models.product import Product  # noqa: F401
from app.models.sales_data import SalesData  # noqa: F401
from app.models.forecast import Forecast  # noqa: F401
from app.models.forecast_result import ForecastResult  # noqa: F401
from app.models.csv_upload_session import CsvUploadSession  # noqa: F401
from app.models.activity_log import ActivityLog  # noqa: F401
from app.models.custom_holiday import CustomHoliday  # noqa: F401
