"""
CamelModel — base Pydantic model for automatic snake_case ↔ camelCase conversion.

Every Pydantic schema in the project MUST extend CamelModel instead of BaseModel.

- JSON output uses camelCase  (e.g. totalItems, createdAt)
- JSON input accepts camelCase (e.g. forecastPeriod, productId)
- Python code uses snake_case internally (e.g. total_items, created_at)
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that converts snake_case ↔ camelCase automatically."""

    model_config = ConfigDict(
        alias_generator=to_camel,   # snake_case → camelCase for JSON keys
        populate_by_name=True,      # Accept both snake_case and camelCase as input
    )
