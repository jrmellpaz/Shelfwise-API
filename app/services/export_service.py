"""
Export Service — generate downloadable forecast exports.

Supports:
- CSV export of forecast result data points
- Chart PNG export (matplotlib)
- PDF report export (reportlab)
"""

import io
import csv
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_csv_export(results) -> io.BytesIO:
    """Build a CSV file from forecast result records.

    Args:
        results: List of ForecastResult ORM objects.

    Returns:
        A BytesIO buffer containing UTF-8 encoded CSV data with columns:
        date, predicted_value, lower_bound, upper_bound
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "predicted_value", "lower_bound", "upper_bound"])

    for r in results:
        writer.writerow([
            r.date.isoformat() if r.date else "",
            round(r.predicted_value, 2) if r.predicted_value is not None else "",
            round(r.lower_bound_80, 2) if r.lower_bound_80 is not None else "",
            round(r.upper_bound_80, 2) if r.upper_bound_80 is not None else "",
        ])

    # Convert to bytes for StreamingResponse
    output = io.BytesIO(buffer.getvalue().encode("utf-8"))
    output.seek(0)
    return output


def _aggregate_historical(historical_data, granularity: str):
    """Aggregate raw daily SalesData records to match forecast granularity."""
    import pandas as pd

    if not historical_data or granularity == "daily":
        dates = [r.date for r in historical_data]
        values = [float(r.quantity_sold) for r in historical_data]
        return dates, values

    df = pd.DataFrame({
        "ds": pd.to_datetime([r.date for r in historical_data]),
        "y": [float(r.quantity_sold) for r in historical_data],
    })

    freq = "W" if granularity == "weekly" else "MS"
    df = df.set_index("ds").resample(freq).sum().reset_index()

    return df["ds"].dt.date.tolist(), df["y"].tolist()


def generate_chart_png(forecast, results, historical_data=None) -> io.BytesIO:
    """Render a forecast chart as a PNG image.

    Shows historical data (if provided), prediction line, and
    95% confidence band.

    Args:
        forecast: Forecast ORM object (for metadata).
        results: List of ForecastResult ORM objects.
        historical_data: Optional list of SalesData ORM objects.

    Returns:
        BytesIO buffer containing the PNG image.
    """
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, ax = plt.subplots(figsize=(12, 5))

    # Plot historical data if provided, aggregated to match forecast granularity
    if historical_data:
        granularity = getattr(forecast, "time_granularity", "daily") or "daily"
        hist_dates, hist_values = _aggregate_historical(historical_data, granularity)
        ax.plot(hist_dates, hist_values, color="#4A90D9", linewidth=1.2,
                label="Historical", alpha=0.8)

    # Plot forecast
    fc_dates = [r.date for r in results]
    fc_values = [float(r.predicted_value) for r in results]
    fc_lower = [float(r.lower_bound_80) if r.lower_bound_80 else 0 for r in results]
    fc_upper = [float(r.upper_bound_80) if r.upper_bound_80 else 0 for r in results]

    ax.plot(fc_dates, fc_values, color="#E8553D", linewidth=2, label="Forecast")
    ax.fill_between(fc_dates, fc_lower, fc_upper,
                     color="#E8553D", alpha=0.15, label="80% CI")

    # Formatting
    ax.set_xlabel("Date")
    ax.set_ylabel("Quantity")
    ax.set_title("Demand Forecast")
    ax.legend(loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_pdf_report(forecast, product, user, results, historical_data=None) -> io.BytesIO:
    """Generate a multi-page PDF report for a forecast.

    Includes:
    1. Cover page (product name, date, business name)
    2. Forecast chart
    3. AI explanation text
    4. Key metrics table
    5. Data summary

    Args:
        forecast: Forecast ORM object.
        product: Product ORM object.
        user: User ORM object.
        results: List of ForecastResult ORM objects.
        historical_data: Optional list of SalesData ORM objects.

    Returns:
        BytesIO buffer containing the PDF.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch, mm
    from reportlab.platypus import (
        Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()
    elements = []

    # Custom styles
    title_style = ParagraphStyle(
        "CoverTitle", parent=styles["Title"],
        fontSize=24, spaceAfter=12,
    )
    subtitle_style = ParagraphStyle(
        "CoverSubtitle", parent=styles["Normal"],
        fontSize=14, textColor=colors.grey, spaceAfter=6,
    )
    heading_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"],
        spaceBefore=18, spaceAfter=8,
    )
    body_style = styles["Normal"]

    # ── Cover Page ────────────────────────────────────────────
    elements.append(Spacer(1, 1.5 * inch))
    elements.append(Paragraph("Forecast Report", title_style))

    product_label = f"{product.name} ({product.product_id})" if product else "Unknown Product"
    elements.append(Paragraph(product_label, subtitle_style))

    business = user.name if user and user.name else ""
    if business:
        elements.append(Paragraph(business, subtitle_style))

    date_str = forecast.forecast_date.strftime("%B %d, %Y") if forecast.forecast_date else "N/A"
    elements.append(Paragraph(f"Generated: {date_str}", subtitle_style))
    elements.append(Spacer(1, 0.5 * inch))

    # ── Forecast Chart ────────────────────────────────────────
    if results:
        elements.append(Paragraph("Forecast Chart", heading_style))
        chart_buf = generate_chart_png(forecast, results, historical_data)
        img = Image(chart_buf, width=6.5 * inch, height=2.7 * inch)
        elements.append(img)
        elements.append(Spacer(1, 0.3 * inch))

    # ── AI Explanation ────────────────────────────────────────
    if forecast.ai_explanation:
        elements.append(Paragraph("AI-Generated Insights", heading_style))
        try:
            explanation = json.loads(forecast.ai_explanation) if isinstance(
                forecast.ai_explanation, str
            ) else forecast.ai_explanation

            if isinstance(explanation, dict):
                summary = explanation.get("summary", "")
                if summary:
                    elements.append(Paragraph(summary, body_style))
                    elements.append(Spacer(1, 6))

                highlights = explanation.get("highlights", [])
                if highlights:
                    elements.append(Paragraph("<b>Key Highlights:</b>", body_style))
                    for h in highlights:
                        elements.append(Paragraph(f"• {h}", body_style))
                    elements.append(Spacer(1, 6))

                recommendations = explanation.get("recommendations", [])
                if recommendations:
                    elements.append(Paragraph("<b>Recommendations:</b>", body_style))
                    for r in recommendations:
                        elements.append(Paragraph(f"• {r}", body_style))
                    elements.append(Spacer(1, 6))

                risks = explanation.get("risks", [])
                if risks:
                    elements.append(Paragraph("<b>Risks:</b>", body_style))
                    for r in risks:
                        elements.append(Paragraph(f"• {r}", body_style))
            else:
                elements.append(Paragraph(str(explanation), body_style))
        except (json.JSONDecodeError, TypeError):
            elements.append(Paragraph(str(forecast.ai_explanation), body_style))

        elements.append(Spacer(1, 0.3 * inch))

    # ── Metrics Table ─────────────────────────────────────────
    elements.append(Paragraph("Accuracy Metrics", heading_style))
    metrics_data = [["Metric", "Value"]]
    for label, attr in [
        ("MAPE", "mape"), ("WAPE", "wape"), ("sMAPE", "smape"),
        ("MASE", "mase"), ("RMSE", "rmse"), ("MAE", "mae"),
    ]:
        val = getattr(forecast, attr, None)
        if val is not None:
            display = f"{val:.2f}%" if attr in ("mape", "wape", "smape") else f"{val:.2f}"
            metrics_data.append([label, display])

    if len(metrics_data) > 1:
        table = Table(metrics_data, colWidths=[2 * inch, 2 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4A90D9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ]))
        elements.append(table)
    elements.append(Spacer(1, 0.3 * inch))

    # ── Data Summary ──────────────────────────────────────────
    elements.append(Paragraph("Data Summary", heading_style))
    summary_data = [
        ["Forecast Horizon", f"{forecast.forecast_horizon} days"],
        ["Time Granularity", forecast.time_granularity or "daily"],
        ["Selected Model", forecast.selected_model or "N/A"],
        ["Demand Profile", forecast.demand_profile or "N/A"],
        ["Data Range", f"{forecast.data_start_date} – {forecast.data_end_date}"
         if forecast.data_start_date and forecast.data_end_date else "N/A"],
        ["Data Points", str(forecast.data_row_count or "N/A")],
    ]
    summary_table = Table(
        [["Parameter", "Value"]] + summary_data,
        colWidths=[2.5 * inch, 3.5 * inch],
    )
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4A90D9")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
    ]))
    elements.append(summary_table)

    doc.build(elements)
    buf.seek(0)
    return buf
