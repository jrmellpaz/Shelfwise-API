"""
Chatbot Service — Stateless conversational AI for forecast results.

Uses Gemini to answer user questions about a specific forecast.
The frontend sends conversation history with each request;
nothing is persisted server-side.
"""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AIServiceException, NotFoundException, ValidationException
from app.models.forecast import Forecast
from app.models.forecast_result import ForecastResult
from app.models.product import Product
from app.models.sales_data import SalesData

logger = logging.getLogger(__name__)


def _summarize_historical(sales_rows) -> dict:
    """Build a concise statistical summary of historical sales data."""
    if not sales_rows:
        return {"available": False}

    values = [float(r.quantity_sold) for r in sales_rows if r.quantity_sold is not None]
    if not values:
        return {"available": False}

    return {
        "available": True,
        "totalDays": len(values),
        "dateRange": f"{sales_rows[0].date} to {sales_rows[-1].date}",
        "avgDaily": round(sum(values) / len(values), 1),
        "minDaily": round(min(values), 1),
        "maxDaily": round(max(values), 1),
        "totalVolume": round(sum(values), 0),
    }


def _summarize_forecast_results(results) -> dict:
    """Build a concise summary of forecast result data points."""
    if not results:
        return {"available": False}

    predictions = [float(r.predicted_value) for r in results if r.predicted_value is not None]
    if not predictions:
        return {"available": False}

    return {
        "available": True,
        "totalDays": len(predictions),
        "dateRange": f"{results[0].date} to {results[-1].date}",
        "avgPredicted": round(sum(predictions) / len(predictions), 1),
        "minPredicted": round(min(predictions), 1),
        "maxPredicted": round(max(predictions), 1),
        "totalVolume": round(sum(predictions), 0),
        "firstFew": [
            {"date": str(r.date), "predicted": round(float(r.predicted_value), 1)}
            for r in results[:5]
        ],
        "lastFew": [
            {"date": str(r.date), "predicted": round(float(r.predicted_value), 1)}
            for r in results[-5:]
        ],
    }


def build_chat_system_prompt(
    forecast: Forecast,
    product: Product | None,
    results: list,
    sales_data: list,
) -> str:
    """Construct a rich system prompt giving Gemini full forecast context."""

    historical_summary = _summarize_historical(sales_data)
    forecast_summary = _summarize_forecast_results(results)

    product_name = product.name if product else "Unknown"
    product_id = product.product_id if product else "N/A"

    # Build metrics block
    metrics_block = {
        "mape": forecast.mape,
        "wape": forecast.wape,
        "smape": forecast.smape,
        "mase": forecast.mase,
        "rmse": forecast.rmse,
        "mae": forecast.mae,
    }

    # Parse existing AI explanation if available
    ai_explanation = ""
    if forecast.ai_explanation:
        try:
            explanation = json.loads(forecast.ai_explanation) if isinstance(forecast.ai_explanation, str) else forecast.ai_explanation
            ai_explanation = f"\nEXISTING AI ANALYSIS:\n{json.dumps(explanation, indent=2)}"
        except (json.JSONDecodeError, TypeError):
            ai_explanation = f"\nEXISTING AI ANALYSIS:\n{forecast.ai_explanation}"

    prompt = f"""You are a friendly, knowledgeable business advisor embedded in an inventory forecasting app called ShelfWise. You're helping a business owner understand their product forecast results.

RULES:
- Be conversational and helpful. Use "you" and "your".
- Keep responses concise (2-4 short paragraphs max) unless the user asks for detail.
- NEVER use technical jargon like "MAPE", "RMSE", "regressors", "confidence interval", "additive/multiplicative seasonality". Instead say things like "accuracy", "margin of error", "patterns", "trends".
- Ground every answer in the actual data below. If you don't know something, say so.
- Format responses in plain text. You may use simple bullet points when listing things.
- If the user asks about something unrelated to this forecast or their business, politely redirect.

PRODUCT: {product_name} (ID: {product_id})
FORECAST MODEL: {forecast.selected_model or 'N/A'}
DEMAND TYPE: {forecast.demand_profile or 'N/A'}
FORECAST HORIZON: {forecast.forecast_horizon} days
SEASONALITY MODE: {forecast.seasonality_mode or 'N/A'}

ACCURACY METRICS:
{json.dumps(metrics_block, indent=2)}

HISTORICAL SALES SUMMARY:
{json.dumps(historical_summary, indent=2)}

FORECAST RESULTS SUMMARY:
{json.dumps(forecast_summary, indent=2)}

DATA PERIOD: {forecast.data_start_date} to {forecast.data_end_date} ({forecast.data_row_count or 'N/A'} data points)
{ai_explanation}
"""
    return prompt


def chat_with_forecast(
    forecast_id: str,
    user_message: str,
    history: list[dict[str, str]],
    db: Session,
) -> str:
    """Send a user message (with history) to Gemini, scoped to a forecast.

    Args:
        forecast_id: UUID of the forecast to chat about.
        user_message: The new message from the user.
        history: Previous messages as [{"role": "user"|"assistant", "content": "..."}].
        db: Database session.

    Returns:
        The assistant's reply text.
    """
    # ── Validate Gemini availability ──
    from app.services.gemini_client import get_gemini_client, is_gemini_available

    if not is_gemini_available():
        raise AIServiceException("Gemini API key is not configured")

    try:
        from google.genai.types import Content, GenerateContentConfig, Part
    except ImportError:
        raise AIServiceException("google-genai package is not installed")

    # ── Load forecast data ──
    forecast = db.query(Forecast).filter(Forecast.id == forecast_id).first()
    if not forecast:
        raise NotFoundException("Forecast")

    if forecast.status != "completed":
        raise ValidationException(
            f"Chat is only available for completed forecasts (status: {forecast.status})"
        )

    product = db.query(Product).filter(Product.id == forecast.product_id).first()

    results = (
        db.query(ForecastResult)
        .filter(ForecastResult.forecast_id == forecast.id)
        .order_by(ForecastResult.date)
        .all()
    )

    sales_data = (
        db.query(SalesData)
        .filter(SalesData.product_id == forecast.product_id)
        .order_by(SalesData.date)
        .all()
    )

    # ── Build the prompt ──
    system_prompt = build_chat_system_prompt(forecast, product, results, sales_data)

    # ── Enforce history limits ──
    max_history = settings.CHATBOT_MAX_HISTORY_MESSAGES
    if len(history) > max_history:
        history = history[-max_history:]

    # ── Build Gemini contents array ──
    contents: list[Content] = []

    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Gemini uses "user" and "model" roles
        gemini_role = "model" if role == "assistant" else "user"
        contents.append(Content(role=gemini_role, parts=[Part(text=content)]))

    # Add the new user message
    contents.append(Content(role="user", parts=[Part(text=user_message)]))

    # ── Call Gemini ──
    model_name = settings.GEMINI_MODEL_NAME
    logger.info("Chatbot calling Gemini (%s) for forecast %s", model_name, forecast_id)

    try:
        client = get_gemini_client()
        if client is None:
            raise AIServiceException("Failed to create Gemini client")
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=settings.CHATBOT_TEMPERATURE,
                max_output_tokens=settings.CHATBOT_MAX_OUTPUT_TOKENS,
            ),
        )

        reply = response.text.strip() if response.text else "I wasn't able to generate a response. Please try rephrasing your question."
        logger.info("Chatbot response received (%d chars)", len(reply))
        return reply

    except Exception as e:
        logger.error("Chatbot Gemini API error: %s", e)
        raise AIServiceException(f"Failed to get AI response: {str(e)}")
