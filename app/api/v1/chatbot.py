"""
Chatbot endpoints — /api/v1/forecasts/{id}/chat

POST /forecasts/{id}/chat  — Send a message, get AI response (stateless)
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.forecast import Forecast
from app.models.user import User
from app.core.exceptions import NotFoundException
from app.schemas.common import success_response
from app.schemas.forecast import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{forecast_uuid}/chat")
async def chat_with_forecast(
    forecast_uuid: UUID,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a message to the AI chatbot about a specific forecast.

    The frontend sends the conversation history with each request.
    Nothing is stored server-side — chat resets on page refresh.
    """
    from app.services.chatbot_service import chat_with_forecast as chat_fn

    # Verify forecast belongs to user
    forecast = (
        db.query(Forecast)
        .filter(Forecast.id == forecast_uuid, Forecast.user_id == current_user.id)
        .first()
    )
    if not forecast:
        raise NotFoundException("Forecast")

    reply = chat_fn(
        forecast_id=str(forecast_uuid),
        user_message=body.message,
        history=[msg.model_dump() for msg in body.history],
        db=db,
    )

    return success_response(
        data={
            "reply": reply,
            "role": "assistant",
        },
        message="Chat response generated",
    )
