"""
Gemini Service — AI-generated forecast explanations.

Uses the shared gemini_client helper for client creation and
settings.GEMINI_MODEL_NAME / settings.EXPLANATION_TEMPERATURE for config.
Returns structured dict parsed from Gemini's JSON response.
"""

import json
import logging
import re

from app.config import settings


logger = logging.getLogger(__name__)


def generate_gemini_explanation(frontend_data: dict) -> dict | None:
    """Send forecast context to Gemini and get a structured explanation.

    Returns a dict with keys: overview, patterns, reliability,
    recommendations, risks, nextSteps.  Returns None on failure.
    """
    from app.services.gemini_client import get_gemini_client

    client = get_gemini_client()
    if client is None:
        return None

    # ── Build context from forecast data ──
    metrics = frontend_data.get("metrics", {})
    historical = frontend_data.get("historical", [])
    forecast = frontend_data.get("forecast", [])
    components = frontend_data.get("components", {})
    demand_profile = frontend_data.get("demandProfile", {})

    if not historical or not forecast:
        logger.warning("Insufficient data for Gemini explanation")
        return None

    hist_values = [h["actual"] for h in historical]
    forecast_values = [f["predicted"] for f in forecast]
    lower_bounds = [f.get("lowerBound", 0) for f in forecast]
    upper_bounds = [f.get("upperBound", 0) for f in forecast]

    avg_historical = sum(hist_values) / len(hist_values) if hist_values else 0
    avg_forecast = sum(forecast_values) / len(forecast_values) if forecast_values else 0
    total_forecast_volume = sum(forecast_values)
    total_lower_bound = sum(lower_bounds)
    total_upper_bound = sum(upper_bounds)
    growth_pct = (
        ((avg_forecast - avg_historical) / avg_historical * 100)
        if avg_historical > 0 else 0
    )

    # Confidence band
    mape_val = metrics.get("mape", 0) or 0
    confidence_units = round(avg_historical * (mape_val / 100), 1) if avg_historical > 0 else 0
    confidence_band_text = (
        f"On a typical day selling ~{avg_historical:.0f} units, "
        f"this forecast could be off by about ±{confidence_units} units."
    )

    # Recent momentum
    if len(hist_values) >= 60:
        last_30 = hist_values[-30:]
        prior_30 = hist_values[-60:-30]
        avg_last = sum(last_30) / len(last_30)
        avg_prior = sum(prior_30) / len(prior_30)
        mom_pct = ((avg_last - avg_prior) / avg_prior * 100) if avg_prior > 0 else 0
        if mom_pct > 1:
            momentum_text = f"Sales over the last 30 days averaged {avg_last:.1f} units/day, up {mom_pct:+.1f}% vs prior 30 days."
        elif mom_pct < -1:
            momentum_text = f"Sales over the last 30 days averaged {avg_last:.1f} units/day, down {mom_pct:+.1f}% vs prior 30 days."
        else:
            momentum_text = f"Sales over the last 30 days averaged {avg_last:.1f} units/day, essentially flat vs prior 30 days."
    else:
        momentum_text = "Not enough data to compare recent vs prior 30-day performance."

    # Weekly/yearly patterns
    weekly = components.get("weekly", [])
    yearly = components.get("yearly", [])
    peak_day = max(weekly, key=lambda x: x["effect"])["dayOfWeek"] if weekly else "N/A"
    low_day = min(weekly, key=lambda x: x["effect"])["dayOfWeek"] if weekly else "N/A"
    peak_month = max(yearly, key=lambda x: x["effect"])["month"] if yearly else "N/A"
    low_month = min(yearly, key=lambda x: x["effect"])["month"] if yearly else "N/A"

    # Trend changes
    trend_changes = frontend_data.get("trendChanges", [])
    trend_changes_text = "\n".join(
        f"- {tc['date']}: Trend {tc['direction']} by {tc['magnitude']} units/day"
        for tc in trend_changes
    ) or "- No major trend shifts detected"

    # ── Construct the prompt ──
    prompt = f"""You are a friendly business advisor helping a small business owner understand their sales forecast.
Write in conversational, everyday language. Speak directly to the business owner using "you" and "your".

LANGUAGE RULES:
- Do NOT open with greetings. Jump straight into the insight.
- NEVER use: "baseline", "regressors", "confidence bound", "error rate", "variance", "seasonality", "interpolation", "additive", "multiplicative".
- Instead say: "usual", "normal", "slow scenario", "best-case", "worst-case", "pattern", "trend".

Here is the forecast data:

PRODUCT: {frontend_data.get('productName', 'Unknown')} ({frontend_data.get('productId', '')})
HISTORICAL PERIOD: {historical[0]['date']} to {historical[-1]['date']} ({len(historical)} days)
FORECAST PERIOD: {forecast[0]['date']} to {forecast[-1]['date']} ({len(forecast)} days)

KEY NUMBERS:
- Average daily sales (past): {avg_historical:.1f} units
- Average daily sales (future): {avg_forecast:.1f} units
- Total projected volume: {total_forecast_volume:.0f} units
- Slow scenario: {total_lower_bound:.0f} units
- Best-case scenario: {total_upper_bound:.0f} units
- Expected growth/decline: {growth_pct:+.1f}%

RECENT MOMENTUM:
{momentum_text}

ACCURACY: {confidence_band_text}
DEMAND TYPE: {demand_profile.get('classification', 'unknown')}

PATTERNS:
- Busiest day: {peak_day}
- Slowest day: {low_day}
- Busiest month: {peak_month}
- Slowest month: {low_month}

RECENT TREND SHIFTS:
{trend_changes_text}

Respond with a JSON object containing:
- "overview": 1-2 sentence summary with projected total volume
- "patterns": description of day-of-week and monthly patterns
- "reliability": how reliable this forecast is, in plain terms
- "recommendations": array of 3-5 actionable inventory recommendations
- "risks": array of 2-3 specific risks based on the data
- "nextSteps": array of 2-3 concrete next steps for this week
"""

    # ── Response schema ──
    response_schema = {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "patterns": {"type": "string"},
            "reliability": {"type": "string"},
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "nextSteps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["overview", "patterns", "reliability", "recommendations", "risks", "nextSteps"],
    }

    # ── Call Gemini ──
    model_name = settings.GEMINI_MODEL_NAME
    logger.info("Calling Gemini (%s)...", model_name)
    try:
        from google.genai.types import GenerateContentConfig

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=settings.EXPLANATION_TEMPERATURE,
            ),
        )
        explanation = json.loads(response.text)
        logger.info("Gemini explanation received successfully")
        return explanation

    except json.JSONDecodeError:
        logger.warning("Gemini returned invalid JSON")
        return None
    except Exception as e:
        logger.error("Gemini API error: %s", e)
        return None
