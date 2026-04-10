"""
============================================================
FORECASTING PIPELINE TEST SCRIPT
============================================================
End-to-end pipeline: CSV → Validate → Preprocess → Prophet
→ Cross-Validation → Gemini Explanation → Results

Usage:
    python pipeline_test.py --csv sample_sales_data.csv
    python pipeline_test.py --csv sample_sales_data.csv --product SKU-001
    python pipeline_test.py --csv sample_sales_data.csv --skip-gemini
    python pipeline_test.py --csv sample_sales_data.csv --horizon 90 --country PH

Output data is shaped for frontend charting (JSON-ready).
Backend sends raw numbers → Frontend renders interactive charts.
============================================================
"""

import argparse
import json
import logging
import math
import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import requests

import numpy as np
import pandas as pd

# Suppress Prophet's verbose logging (Stan compiler messages)
warnings.filterwarnings("ignore", category=FutureWarning)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics

# Load environment variables from .env file (for GEMINI_API_KEY)
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# STEP 1: LOAD CSV
# ============================================================


def load_csv(file_path: str, column_map: dict | None = None) -> pd.DataFrame:
    """
    Load a CSV file and return it as a pandas DataFrame.

    This is the entry point of the pipeline. The CSV is expected
    to have columns: date, product_id, product_name, quantity_sold.
    We do NOT enforce column names here — that happens in validation.
    """
    path = Path(file_path)
    if not path.exists():
        print(f"  ✗ File not found: {path.resolve()}")
        sys.exit(1)

    # Check file size (enforce 10MB limit per BACKEND_REFERENCE)
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 10:
        print(f"  ✗ File too large: {size_mb:.1f}MB (max 10MB)")
        sys.exit(1)

    df = pd.read_csv(path)

    # Apply column mapping if provided
    if column_map:
        # Create a dict for pandas rename: {original_name: standard_name}
        rename_dict = {
            column_map["date"]: "date",
            column_map["product_id"]: "product_id",
            column_map["quantity_sold"]: "quantity_sold",
        }

        # Only add product_name to mapping if the original column exists in the DataFrame
        # or if they explicitly mapped it to something other than the default "product_name"
        mapped_name_col = column_map.get("product_name")
        if mapped_name_col in df.columns:
            rename_dict[mapped_name_col] = "product_name"

        df = df.rename(columns=rename_dict)

    # Crucial Fallback: If product_name is still missing (like in the Kaggle dataset),
    # duplicate the product_id column to serve as the name so the pipeline doesn't fail.
    # We do this here before validation.
    if "product_name" not in df.columns and "product_id" in df.columns:
        print(f"  ⚠ 'product_name' column missing. Using 'product_id' as fallback.")
        df["product_name"] = df["product_id"].astype(str)

    # Check row count (enforce 50K limit per BACKEND_REFERENCE)
    if len(df) > 50_000:
        print(f"  ✗ Too many rows: {len(df):,} (max 50,000)")
        sys.exit(1)

    print(f"  ✓ Loaded {len(df):,} rows from {path.name} ({size_mb:.1f}MB)")
    return df


# ============================================================
# STEP 2: VALIDATE STRUCTURE
# ============================================================

REQUIRED_COLUMNS = ["date", "product_id", "product_name", "quantity_sold"]


def validate_structure(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Check that the CSV has the required columns and correct types.
    Cleans recoverable issues in-place and returns warnings.

    Handles:
    - Missing required columns (fatal)
    - Extra/unexpected columns (ignored with warning)
    - NaN/null values in date → rows dropped
    - NaN/null values in quantity_sold → coerced to 0
    - Empty strings and whitespace → treated as NaN
    - Data type mismatches in quantity_sold → coerced to 0
    - Negative values in quantity_sold → clamped to 0
    - Unparseable dates → rows dropped

    Returns:
        Tuple of (cleaned DataFrame, list of warning messages)
    """
    warnings_list = []
    df = df.copy()

    # ---- Check required columns exist ----
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        print(f"  ✗ Missing required columns: {missing_cols}")
        print(f"    Found columns: {list(df.columns)}")
        sys.exit(1)

    print(f"  ✓ All required columns present: {REQUIRED_COLUMNS}")

    # ---- Warn about extra columns (non-fatal) ----
    extra_cols = [c for c in df.columns if c not in REQUIRED_COLUMNS]
    if extra_cols:
        warnings_list.append(f"Extra columns ignored: {extra_cols}")
        print(f"  ⚠ Extra columns found (will be ignored): {extra_cols}")

    # ---- Handle empty strings and whitespace ----
    # Replace empty strings and whitespace-only strings with NaN
    # so they are caught by subsequent null checks
    for col in REQUIRED_COLUMNS:
        if df[col].dtype == object:
            mask = df[col].astype(str).str.strip().isin(["", "nan", "null", "None"])
            n_empty = mask.sum()
            if n_empty > 0:
                df.loc[mask, col] = np.nan
                warnings_list.append(
                    f"{n_empty} empty/whitespace values in '{col}' → treated as NaN"
                )
                print(
                    f"  ⚠ {n_empty} empty/whitespace values in '{col}' treated as NaN"
                )

    # ---- Handle null dates ----
    null_dates = df["date"].isna().sum()
    if null_dates > 0:
        warnings_list.append(f"{null_dates} null date values → rows dropped")
        print(f"  ⚠ Dropping {null_dates} rows with null dates")
        df = df.dropna(subset=["date"])

    # ---- Handle unparseable dates ----
    original_len = len(df)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    unparseable = df["date"].isna().sum()
    if unparseable > 0:
        warnings_list.append(f"{unparseable} unparseable date values → rows dropped")
        print(f"  ⚠ Dropping {unparseable} rows with unparseable dates")
        df = df.dropna(subset=["date"])

    # ---- Handle future dates ----
    today = pd.Timestamp.now().normalize()
    future_mask = df["date"] > today
    n_future = future_mask.sum()
    if n_future > 0:
        warnings_list.append(f"{n_future} future-dated rows → dropped")
        print(f"  ⚠ Dropping {n_future} rows with future dates (after {today.date()})")
        df = df[~future_mask]

    # ---- Handle type mismatches in quantity_sold ----
    # Coerce to numeric — non-numeric values become NaN
    original_qty = df["quantity_sold"].copy()
    df["quantity_sold"] = pd.to_numeric(df["quantity_sold"], errors="coerce")
    n_coerced = df["quantity_sold"].isna().sum()
    if n_coerced > 0:
        warnings_list.append(
            f"{n_coerced} non-numeric values in quantity_sold → set to 0"
        )
        print(f"  ⚠ {n_coerced} non-numeric quantity_sold values coerced to 0")
        df["quantity_sold"] = df["quantity_sold"].fillna(0)

    # ---- Handle negative values ----
    negatives = (df["quantity_sold"] < 0).sum()
    if negatives > 0:
        warnings_list.append(
            f"{negatives} negative values in quantity_sold → clamped to 0"
        )
        print(f"  ⚠ {negatives} negative quantity_sold values clamped to 0")
        df["quantity_sold"] = df["quantity_sold"].clip(lower=0)

    # ---- Final null check on quantity_sold ----
    remaining_nulls = df["quantity_sold"].isna().sum()
    if remaining_nulls > 0:
        df["quantity_sold"] = df["quantity_sold"].fillna(0)

    df = df.reset_index(drop=True)
    print(f"  ✓ Validation complete: {len(df)} clean rows")

    return df, warnings_list


# ============================================================
# STEP 3: DATA QUALITY ASSESSMENT
# ============================================================


def assess_data_quality(
    df: pd.DataFrame, validation_warnings: list[str] | None = None
) -> dict:
    """
    Generate a comprehensive data quality report.

    This report helps users understand their data before forecasting.
    The frontend would display these metrics as a "Data Health" card.

    Args:
        df: The validated/cleaned DataFrame
        validation_warnings: Warnings from the validation step
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    products = df["product_id"].unique()
    date_min = df["date"].min()
    date_max = df["date"].max()
    date_range_days = (date_max - date_min).days

    # Detect duplicates (same date + product_id)
    duplicates = df.duplicated(subset=["date", "product_id"], keep=False)
    num_duplicates = duplicates.sum()

    # Missing values across all columns
    missing_values = df.isnull().sum().to_dict()

    # Detect zero-sales products
    zero_sales_products = []

    # Per-product stats
    product_stats = {}
    for pid in sorted(products):
        pdf = df[df["product_id"] == pid]
        p_dates = pdf["date"].nunique()
        expected_dates = (pdf["date"].max() - pdf["date"].min()).days + 1
        completeness = (p_dates / expected_dates * 100) if expected_dates > 0 else 0
        months_of_data = (pdf["date"].max() - pdf["date"].min()).days / 30.44
        avg_sales = round(float(pdf["quantity_sold"].mean()), 1)
        is_zero_sales = avg_sales == 0 or pdf["quantity_sold"].sum() == 0

        if is_zero_sales:
            zero_sales_products.append(pid)

        product_stats[pid] = {
            "name": pdf["product_name"].iloc[0],
            "rows": len(pdf),
            "unique_dates": p_dates,
            "expected_dates": expected_dates,
            "completeness_pct": round(completeness, 1),
            "months_of_data": round(months_of_data, 1),
            "has_sufficient_data": months_of_data >= 6,
            "avg_daily_sales": avg_sales,
            "is_zero_sales": is_zero_sales,
        }

    report = {
        "total_rows": len(df),
        "total_products": len(products),
        "date_range": f"{date_min.strftime('%Y-%m-%d')} → {date_max.strftime('%Y-%m-%d')}",
        "date_range_days": date_range_days,
        "duplicates_found": num_duplicates,
        "missing_values": missing_values,
        "zero_sales_products": zero_sales_products,
        "validation_warnings": validation_warnings or [],
    }

    # Attach per-product stats
    report["product_stats"] = product_stats

    # Print the report
    print(f"  Total rows:        {report['total_rows']:,}")
    print(f"  Products found:    {report['total_products']}")
    print(f"  Date range:        {report['date_range']} ({date_range_days} days)")
    print(f"  Duplicates:        {num_duplicates}")
    print(f"  Missing values:    {missing_values}")

    if zero_sales_products:
        print(f"  ⚠ Zero-sales products: {zero_sales_products}")

    if validation_warnings:
        print(f"\n  Data issues cleaned during validation:")
        for w in validation_warnings:
            print(f"    ⚠ {w}")

    print(f"\n  Per-product breakdown:")
    for pid, stats in product_stats.items():
        if stats["is_zero_sales"]:
            status = "⚠"
            suffix = " [ZERO SALES]"
        elif stats["has_sufficient_data"]:
            status = "✓"
            suffix = ""
        else:
            status = "⚠"
            suffix = " [SHORT HISTORY]"
        print(
            f"    {status} {pid} ({stats['name']}): "
            f"{stats['months_of_data']}mo, "
            f"{stats['completeness_pct']}% complete, "
            f"avg {stats['avg_daily_sales']} units/day{suffix}"
        )

    return report


def build_data_health_scorecard(
    df: pd.DataFrame,
    quality_report: dict,
    validation_warnings: list[str],
) -> dict:
    """
    Build a structured data health scorecard for frontend display.

    Scores data quality on a 0-100 scale across four categories:
    - Completeness: Are there gaps in the data? Missing dates?
    - Consistency: Were there issues to fix (dupes, type errors)?
    - Freshness: How recent is the most recent data point?
    - Volume: Is there enough data for reliable forecasting?

    The overall score is a weighted average of all four.
    This runs during validation (before forecasting) so it can
    be returned to the frontend as a pre-check if desired.
    """
    # ---- Completeness (weight: 30%) ----
    # Based on average completeness across all products
    product_stats = quality_report.get("product_stats", {})
    if product_stats:
        avg_completeness = sum(
            s["completeness_pct"] for s in product_stats.values()
        ) / len(product_stats)
    else:
        avg_completeness = 0

    completeness_score = min(100, round(avg_completeness))
    total_expected = sum(s.get("expected_dates", 0) for s in product_stats.values())
    total_actual = sum(s.get("unique_dates", 0) for s in product_stats.values())
    missing_dates = total_expected - total_actual
    completeness_detail = (
        f"{missing_dates} missing date entries across {len(product_stats)} products"
    )

    # ---- Consistency (weight: 25%) ----
    # Start at 100, deduct for each issue found
    n_issues = len(validation_warnings)
    consistency_score = max(0, 100 - (n_issues * 10))
    consistency_detail = (
        f"{n_issues} issues cleaned during validation"
        if n_issues > 0
        else "No data quality issues found"
    )

    # ---- Freshness (weight: 20%) ----
    # How recent is the latest data?
    df_copy = df.copy()
    df_copy["date"] = pd.to_datetime(df_copy["date"])
    most_recent = df_copy["date"].max()
    days_since_latest = (pd.Timestamp.now() - most_recent).days
    if days_since_latest <= 1:
        freshness_score = 100
    elif days_since_latest <= 7:
        freshness_score = 90
    elif days_since_latest <= 30:
        freshness_score = 70
    elif days_since_latest <= 90:
        freshness_score = 50
    else:
        freshness_score = max(0, 30 - (days_since_latest - 90) // 30 * 10)
    freshness_detail = f"Most recent data: {most_recent.strftime('%Y-%m-%d')} ({days_since_latest} days ago)"

    # ---- Volume (weight: 25%) ----
    # Based on months of data — 24+ months = 100, 6 months = 50
    if product_stats:
        avg_months = sum(s["months_of_data"] for s in product_stats.values()) / len(
            product_stats
        )
    else:
        avg_months = 0
    if avg_months >= 24:
        volume_score = 100
    elif avg_months >= 12:
        volume_score = 80
    elif avg_months >= 6:
        volume_score = 60
    elif avg_months >= 3:
        volume_score = 40
    else:
        volume_score = 20
    volume_detail = f"{avg_months:.1f} months average history (recommended: 12+)"

    # ---- Overall score (weighted average) ----
    overall = round(
        completeness_score * 0.30
        + consistency_score * 0.25
        + freshness_score * 0.20
        + volume_score * 0.25
    )

    # Rating
    if overall >= 90:
        rating = "Excellent"
    elif overall >= 70:
        rating = "Good"
    elif overall >= 50:
        rating = "Fair"
    else:
        rating = "Poor"

    scorecard = {
        "overallScore": overall,
        "rating": rating,
        "categories": {
            "completeness": {
                "score": completeness_score,
                "details": completeness_detail,
            },
            "consistency": {
                "score": consistency_score,
                "details": consistency_detail,
            },
            "freshness": {
                "score": freshness_score,
                "details": freshness_detail,
            },
            "volume": {
                "score": volume_score,
                "details": volume_detail,
            },
        },
        "issuesFixed": validation_warnings,
        "warnings": [
            f"{pid} has only {s['months_of_data']}mo of data"
            for pid, s in product_stats.items()
            if not s["has_sufficient_data"]
        ]
        + [
            f"{pid} has zero sales"
            for pid, s in product_stats.items()
            if s["is_zero_sales"]
        ],
    }

    # Print scorecard
    print(f"\n  {'─' * 40}")
    print(f"  DATA HEALTH SCORECARD")
    print(f"  {'─' * 40}")
    print(f"  Overall: {overall}/100 ({rating})")
    print(f"    Completeness: {completeness_score}/100 — {completeness_detail}")
    print(f"    Consistency:  {consistency_score}/100 — {consistency_detail}")
    print(f"    Freshness:    {freshness_score}/100 — {freshness_detail}")
    print(f"    Volume:       {volume_score}/100 — {volume_detail}")

    return scorecard


# ============================================================
# STEP 3.5: FETCH WEATHER DATA (OPEN-METEO)
# ============================================================


def fetch_weather_data(
    start_date: str,
    end_date: str,
    latitude: float = 14.5995,
    longitude: float = 120.9842,
) -> pd.DataFrame | None:
    """
    Fetch historical daily weather data from the Open-Meteo API.

    Open-Meteo is a free, no-API-key weather service with historical
    data going back to 1940. We fetch daily mean temperature and
    precipitation, which can be used as extra regressors in Prophet
    to improve forecast accuracy.

    Args:
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format
        latitude: Location latitude (default: Manila, Philippines)
        longitude: Location longitude (default: Manila, Philippines)

    Returns:
        DataFrame with columns 'ds', 'temperature', 'precipitation'
        or None if the API call fails
    """
    # Open-Meteo Historical Weather API (archive endpoint)
    # Docs: https://open-meteo.com/en/docs/historical-weather-api
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": ["temperature_2m_mean", "precipitation_sum"],
        "timezone": "auto",
    }

    try:
        print(f"  Fetching weather data from Open-Meteo...")
        print(f"    Location: ({latitude}, {longitude})")
        print(f"    Date range: {start_date} → {end_date}")
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        weather_df = pd.DataFrame(
            {
                "ds": pd.to_datetime(data["daily"]["time"]),
                "temperature": data["daily"]["temperature_2m_mean"],
                "precipitation": data["daily"]["precipitation_sum"],
            }
        )

        # Fill any missing weather values with forward-fill
        weather_df = weather_df.ffill().bfill()

        print(f"  ✓ Fetched {len(weather_df)} days of weather data")
        print(
            f"    Temperature range: {weather_df['temperature'].min():.1f}°C – {weather_df['temperature'].max():.1f}°C"
        )
        print(f"    Avg precipitation: {weather_df['precipitation'].mean():.1f} mm/day")
        return weather_df

    except requests.exceptions.RequestException as e:
        print(f"  ⚠ Failed to fetch weather data: {e}")
        print(f"    Pipeline will continue without weather regressors.")
        return None
    except (KeyError, ValueError) as e:
        print(f"  ⚠ Error parsing weather data: {e}")
        print(f"    Pipeline will continue without weather regressors.")
        return None


def fetch_forecast_weather(
    start_date: str,
    end_date: str,
    latitude: float = 14.5995,
    longitude: float = 120.9842,
) -> pd.DataFrame | None:
    """
    Fetch forecast weather data from the Open-Meteo Forecast API.

    For the future forecast period, we need predicted weather values.
    Open-Meteo provides up to 16 days of weather forecast for free.
    Beyond that, we use the historical average for the same day-of-year
    as a reasonable approximation.

    Args:
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format
        latitude: Location latitude (default: Manila, Philippines)
        longitude: Location longitude (default: Manila, Philippines)

    Returns:
        DataFrame with columns 'ds', 'temperature', 'precipitation'
        or None if the API call fails
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ["temperature_2m_mean", "precipitation_sum"],
        "timezone": "auto",
        "forecast_days": 16,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        forecast_weather = pd.DataFrame(
            {
                "ds": pd.to_datetime(data["daily"]["time"]),
                "temperature": data["daily"]["temperature_2m_mean"],
                "precipitation": data["daily"]["precipitation_sum"],
            }
        )
        return forecast_weather

    except Exception:
        return None


# ============================================================
# STEP 4: PREPROCESS FOR PROPHET
# ============================================================


def preprocess_for_prophet(
    df: pd.DataFrame,
    product_id: str,
    aggregation: str = "daily",
    weather_data: pd.DataFrame | None = None,
    external_regressors: pd.DataFrame | None = None,
    gap_fill_method: str = "interpolate",
    outlier_method: str = "cap",
    outlier_iqr_multiplier: float = 1.5,
) -> pd.DataFrame:
    """
    Prepare data for a single product for Prophet.

    Steps:
    1. Filter to the selected product
    2. Remove duplicates (keep first occurrence)
    3. Rename columns to Prophet format (ds, y)
    4. Sort by date
    5. Fill missing dates using a configurable strategy
    6. Detect and optionally cap/remove outliers using IQR method
    7. Optionally merge weather regressors
    8. Optionally merge external business regressors
    9. Optionally aggregate to weekly/monthly

    Args:
        df: Full dataset
        product_id: Which product to forecast
        aggregation: 'daily', 'weekly', or 'monthly'
        weather_data: Optional weather DataFrame with 'ds', 'temperature',
            'precipitation' columns for regressor support
        external_regressors: Optional DataFrame with 'ds' plus one or more
            user-provided regressor columns (promo flags, payday flags, etc.)
        gap_fill_method: How to fill missing dates: 'interpolate', 'zero',
            or 'ffill'
        outlier_method: How to handle outliers: 'cap', 'remove', or 'none'
        outlier_iqr_multiplier: IQR multiplier used to identify outliers

    Returns:
        DataFrame with columns 'ds', 'y', and optionally
        'temperature' and 'precipitation' (if weather data provided)
    """
    # Filter to selected product
    pdf = df[df["product_id"] == product_id].copy()
    if pdf.empty:
        print(f"  ✗ No data found for product: {product_id}")
        sys.exit(1)

    product_name = pdf["product_name"].iloc[0]
    print(f"  Product: {product_id} ({product_name})")
    print(f"  Raw rows: {len(pdf)}")

    # Parse dates and remove duplicates
    pdf["date"] = pd.to_datetime(pdf["date"])
    before_dedup = len(pdf)
    pdf = pdf.drop_duplicates(subset=["date"], keep="first")
    dupes_removed = before_dedup - len(pdf)
    if dupes_removed > 0:
        print(f"  ✓ Removed {dupes_removed} duplicate dates")

    # Rename to Prophet format: date→ds, quantity_sold→y
    pdf = pdf.rename(columns={"date": "ds", "quantity_sold": "y"})
    pdf = pdf[["ds", "y"]].sort_values("ds").reset_index(drop=True)

    # Ensure y is numeric and fill any remaining NaN with 0
    pdf["y"] = pd.to_numeric(pdf["y"], errors="coerce").fillna(0)

    # Clamp negative values to 0 (in case any slipped through)
    n_neg = (pdf["y"] < 0).sum()
    if n_neg > 0:
        pdf["y"] = pdf["y"].clip(lower=0)
        print(f"  ✓ Clamped {n_neg} negative values to 0")

    # Prophet needs a continuous date series with no gaps.
    # Different businesses may want different assumptions for missing dates,
    # so the fill strategy is configurable.
    full_range = pd.date_range(start=pdf["ds"].min(), end=pdf["ds"].max(), freq="D")
    pdf = pdf.set_index("ds").reindex(full_range).reset_index()
    pdf.columns = ["ds", "y"]
    n_missing_dates = int(pdf["y"].isna().sum())
    if gap_fill_method == "interpolate":
        pdf["y"] = pdf["y"].interpolate(method="linear").fillna(0)
        if n_missing_dates > 0:
            print(
                f"  ✓ Filled {n_missing_dates} missing dates using linear interpolation"
            )
    elif gap_fill_method == "zero":
        pdf["y"] = pdf["y"].fillna(0)
        if n_missing_dates > 0:
            print(f"  ✓ Filled {n_missing_dates} missing dates with zeros")
    elif gap_fill_method == "ffill":
        pdf["y"] = pdf["y"].ffill().fillna(0)
        if n_missing_dates > 0:
            print(f"  ✓ Filled {n_missing_dates} missing dates using forward fill")
    else:
        raise ValueError(f"Unsupported gap_fill_method: {gap_fill_method}")
    print(f"  ✓ Date range: {pdf['ds'].min().date()} → {pdf['ds'].max().date()}")
    print(f"  ✓ Total days (after gap fill): {len(pdf)}")

    # Outlier detection and handling using IQR method.
    # For sparse/intermittent series, zeros dominate the distribution, so we
    # estimate the IQR on strictly positive values only and skip handling when
    # there is not enough spread to define sensible bounds.
    positive_values = pdf.loc[pdf["y"] > 0, "y"]
    total_outliers = 0
    if len(positive_values) < 8:
        print("  ✓ Skipped outlier handling (not enough positive values)")
    else:
        q1 = positive_values.quantile(0.25)
        q3 = positive_values.quantile(0.75)
        iqr = q3 - q1

        if iqr <= 0:
            print("  ✓ Skipped outlier handling (positive-demand IQR is too small)")
        else:
            lower_bound = max(
                0, q1 - outlier_iqr_multiplier * iqr
            )  # Sales can't be negative
            upper_bound = q3 + outlier_iqr_multiplier * iqr

            positive_mask = pdf["y"] > 0
            outliers_low = ((pdf["y"] < lower_bound) & positive_mask).sum()
            outliers_high = ((pdf["y"] > upper_bound) & positive_mask).sum()
            total_outliers = int(outliers_low + outliers_high)

            if total_outliers > 0 and outlier_method == "cap":
                pdf.loc[positive_mask, "y"] = pdf.loc[positive_mask, "y"].clip(
                    lower=lower_bound,
                    upper=upper_bound,
                )
                print(
                    f"  ✓ Capped {total_outliers} outliers (IQR bounds: {lower_bound:.0f}–{upper_bound:.0f})"
                )
            elif total_outliers > 0 and outlier_method == "remove":
                before_rows = len(pdf)
                pdf = pdf[
                    (~positive_mask)
                    | ((pdf["y"] >= lower_bound) & (pdf["y"] <= upper_bound))
                ].reset_index(drop=True)
                print(
                    f"  ✓ Removed {before_rows - len(pdf)} outlier rows "
                    f"(IQR bounds: {lower_bound:.0f}–{upper_bound:.0f})"
                )
            elif outlier_method == "none":
                print(
                    f"  ✓ Outlier handling disabled ({total_outliers} candidate outliers detected)"
                )
            elif outlier_method not in {"cap", "remove", "none"}:
                raise ValueError(f"Unsupported outlier_method: {outlier_method}")
            else:
                print("  ✓ No outliers detected")

    # Keep unsmoothed daily values so CV metrics reflect raw operational noise.

    # Merge weather regressors if available
    if weather_data is not None:
        pdf = pdf.merge(
            weather_data[["ds", "temperature", "precipitation"]], on="ds", how="left"
        )
        # Forward-fill and back-fill any missing weather values at edges
        pdf["temperature"] = pdf["temperature"].ffill().bfill()
        pdf["precipitation"] = pdf["precipitation"].ffill().bfill()
        print(f"  ✓ Merged weather regressors (temperature, precipitation)")

    # Merge optional user-provided business regressors.
    # Missing values default to 0, which is a sensible baseline for flags.
    if external_regressors is not None and not external_regressors.empty:
        regressor_columns = [c for c in external_regressors.columns if c != "ds"]
        pdf = pdf.merge(external_regressors, on="ds", how="left")
        pdf[regressor_columns] = pdf[regressor_columns].fillna(0)
        print(f"  ✓ Merged external regressors: {', '.join(regressor_columns)}")

    # Time aggregation (if not daily)
    if aggregation == "weekly":
        agg_dict = {"y": "sum"}
        if "temperature" in pdf.columns:
            agg_dict["temperature"] = "mean"
            agg_dict["precipitation"] = "sum"
        for col in [
            c
            for c in pdf.columns
            if c not in {"ds", "y", "temperature", "precipitation"}
        ]:
            agg_dict[col] = "mean"
        pdf = pdf.set_index("ds").resample("W").agg(agg_dict).reset_index()
        print(f"  ✓ Aggregated to weekly: {len(pdf)} data points")
    elif aggregation == "monthly":
        agg_dict = {"y": "sum"}
        if "temperature" in pdf.columns:
            agg_dict["temperature"] = "mean"
            agg_dict["precipitation"] = "sum"
        for col in [
            c
            for c in pdf.columns
            if c not in {"ds", "y", "temperature", "precipitation"}
        ]:
            agg_dict[col] = "mean"
        pdf = pdf.set_index("ds").resample("MS").agg(agg_dict).reset_index()
        print(f"  ✓ Aggregated to monthly: {len(pdf)} data points")
    else:
        print(f"  ✓ Keeping daily granularity: {len(pdf)} data points")

    # Ensure y is float (Prophet requirement) and no NaN
    pdf["y"] = pdf["y"].astype(float)
    assert (
        pdf["y"].isna().sum() == 0
    ), "NaN values found in y column after preprocessing"

    return pdf


# ============================================================
# STEP 5.5: HYPERPARAMETER TUNING (OPTUNA)
# ============================================================


def tune_hyperparameters(
    df: pd.DataFrame,
    n_trials: int = 30,
    use_weather: bool = False,
    country: str | None = None,
    custom_holidays: list[dict] | None = None,
    cv_initial_days: int | None = None,
    cv_horizon_days: int | None = None,
    cv_period_days: int | None = None,
) -> dict:
    """
    Use Optuna (Bayesian optimization) to find the best Prophet
    hyperparameters for this specific product's data.

    Instead of using fixed values for changepoint_prior_scale,
    seasonality_prior_scale, etc., this function tries multiple
    combinations and picks the one with the lowest cross-validation
    MAPE (percentage error).

    Optuna is smart — it learns from previous trials to focus on
    promising parameter regions, typically finding the best config
    in 30-50 trials instead of exhaustively testing hundreds.

    Args:
        df: Preprocessed DataFrame with 'ds' and 'y' columns
        n_trials: Number of parameter combinations to try
            (more = slower but more thorough)
        use_weather: Whether the model includes weather regressors
        country: Country code for holidays

    Returns:
        Dict with best parameters:
        {
            'changepoint_prior_scale': float,
            'seasonality_prior_scale': float,
            'seasonality_mode': str,
            'monthly_fourier_order': int,
            'best_mape': float,
        }
    """
    import optuna

    # Suppress Optuna's verbose logging (we show our own summary)
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    cv_config = determine_cv_config(
        df,
        initial_days=cv_initial_days,
        horizon_days=cv_horizon_days,
        period_days=cv_period_days,
    )
    initial_days = cv_config["initial_days"]
    horizon_days = cv_config["horizon_days"]
    period_days = cv_config["period_days"]

    print(f"  Trials:  {n_trials}")
    print(
        f"  CV config: initial={initial_days}d, horizon={horizon_days}d, "
        f"period={period_days}d"
    )

    def objective(trial):
        """
        Optuna objective function. Each trial proposes a set of
        parameters, trains a Prophet model, runs cross-validation,
        and returns the MAPE. Optuna minimizes this value.
        """
        # Parameters to tune (Optuna picks values from these ranges)
        params = {
            "changepoint_prior_scale": trial.suggest_float(
                "changepoint_prior_scale", 0.001, 0.5, log=True
            ),
            "seasonality_prior_scale": trial.suggest_float(
                "seasonality_prior_scale", 0.1, 10.0, log=True
            ),
            "seasonality_mode": trial.suggest_categorical(
                "seasonality_mode", ["additive", "multiplicative"]
            ),
        }
        monthly_fourier = trial.suggest_int("monthly_fourier_order", 3, 10)
        regressor_columns = [c for c in df.columns if c not in {"ds", "y"}]

        try:
            model = Prophet(
                changepoint_prior_scale=params["changepoint_prior_scale"],
                seasonality_prior_scale=params["seasonality_prior_scale"],
                seasonality_mode=params["seasonality_mode"],
                interval_width=0.95,
                daily_seasonality=False,
                weekly_seasonality=True,
                yearly_seasonality=True,
            )

            # Add monthly seasonality with tunable Fourier order
            model.add_seasonality(
                name="monthly", period=30.5, fourier_order=monthly_fourier
            )

            for col in regressor_columns:
                model.add_regressor(col)

            # Add country holidays
            if country:
                model.add_country_holidays(country_name=country)

            if custom_holidays:
                model.holidays = pd.DataFrame(custom_holidays)

            # Train and cross-validate
            model.fit(df)
            cv_results = cross_validation(
                model,
                initial=f"{initial_days} days",
                period=f"{period_days} days",
                horizon=f"{horizon_days} days",
            )
            metrics = performance_metrics(cv_results)
            mape = float(metrics["mape"].mean())

            return mape

        except Exception:
            # If a parameter combo causes an error, return a bad score
            return float("inf")

    # Run the optimization
    print(f"  Searching for optimal parameters...")
    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    # Extract best parameters
    best = study.best_params
    best["best_mape"] = round(study.best_value * 100, 2)

    print(f"  ✓ Tuning complete! Best MAPE: {best['best_mape']}%")
    print(f"    changepoint_prior_scale: {best['changepoint_prior_scale']:.4f}")
    print(f"    seasonality_prior_scale: {best['seasonality_prior_scale']:.4f}")
    print(f"    seasonality_mode:        {best['seasonality_mode']}")
    print(f"    monthly_fourier_order:   {best['monthly_fourier_order']}")

    return best


# ============================================================
# STEP 6: TRAIN PROPHET MODEL
# ============================================================


def train_prophet(
    df: pd.DataFrame,
    horizon_days: int = 90,
    country: str | None = None,
    custom_holidays: list[dict] | None = None,
    use_weather: bool = False,
    weather_data: pd.DataFrame | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    tuned_params: dict | None = None,
    external_regressors: pd.DataFrame | None = None,
) -> tuple:
    """
    Configure, train Prophet, and generate forecasts.

    Prophet works by decomposing a time series into:
    - Trend: The overall direction (up, down, flat)
    - Seasonality: Repeating patterns (weekly, yearly, monthly)
    - Holidays: Special events that affect sales
    - Regressors: External factors like weather (temperature, precipitation)
    - Residual: Random noise

    Args:
        df: Preprocessed DataFrame with 'ds' and 'y' columns
        horizon_days: How many days into the future to forecast
        country: Country code for built-in holidays (e.g., 'PH')
        custom_holidays: List of dicts with 'name' and 'date' keys
        use_weather: Whether to use weather as an extra regressor
        weather_data: Historical weather DataFrame (used to build
            seasonal averages for forecast period)
        latitude: Location latitude for weather forecast API
        longitude: Location longitude for weather forecast API
        tuned_params: Optional dict from tune_hyperparameters() with
            optimized values for changepoint/seasonality/mode

    Returns:
        Tuple of (model, forecast_df)
    """
    print(f"  Forecast horizon: {horizon_days} days")
    print(f"  Country holidays: {country or 'disabled'}")

    # ---- Initialize Prophet ----
    # seasonality_mode='auto' isn't supported; we detect it ourselves
    # Multiplicative: seasonal effects scale with the trend
    # Additive: seasonal effects are constant regardless of trend
    avg_sales = df["y"].mean()
    std_sales = df["y"].std()
    cv = std_sales / avg_sales if avg_sales > 0 else 0

    # If coefficient of variation is high, use multiplicative
    seasonality_mode = "multiplicative" if cv > 0.5 else "additive"
    # ---- Determine parameters ----
    # If tuned params provided (from Optuna), use those.
    # Otherwise, use sensible defaults.
    if tuned_params:
        cps = tuned_params.get("changepoint_prior_scale", 0.1)
        sps = tuned_params.get("seasonality_prior_scale", 10.0)
        seasonality_mode = tuned_params.get("seasonality_mode", seasonality_mode)
        monthly_fourier = tuned_params.get("monthly_fourier_order", 5)
        print(f"  Using TUNED parameters (from Optuna)")
    else:
        cps = 0.1
        sps = 10.0
        monthly_fourier = 5
        print(f"  Using DEFAULT parameters")

    print(f"  Seasonality mode: {seasonality_mode} (CV={cv:.2f})")

    model = Prophet(
        # Changepoint prior scale controls trend flexibility
        changepoint_prior_scale=cps,
        # Seasonality prior scale controls seasonal pattern strength
        seasonality_prior_scale=sps,
        seasonality_mode=seasonality_mode,
        # Confidence interval width (95% = wider, more conservative)
        interval_width=0.95,
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )

    # ---- Add monthly seasonality ----
    # Captures patterns like end-of-month sales spikes (payday effects)
    # or mid-month lulls that weekly/yearly cycles don't cover.
    model.add_seasonality(name="monthly", period=30.5, fourier_order=monthly_fourier)
    print(
        f"  ✓ Added monthly seasonality (period=30.5, fourier_order={monthly_fourier})"
    )

    regressor_columns = [c for c in df.columns if c not in {"ds", "y"}]
    if regressor_columns:
        for col in regressor_columns:
            model.add_regressor(col)
        print(f"  ✓ Added regressors: {', '.join(regressor_columns)}")

    has_weather = use_weather and "temperature" in df.columns

    # ---- Add country holidays ----
    # Prophet has built-in holidays for many countries.
    # PH = Philippines (includes EDSA Revolution, Rizal Day, etc.)
    if country:
        model.add_country_holidays(country_name=country)
        print(f"  ✓ Added {country} country holidays")

    # ---- Add custom holidays ----
    # Users can define their own special events (store anniversary, sale events)
    if custom_holidays:
        custom_df = pd.DataFrame(custom_holidays)
        custom_df["ds"] = pd.to_datetime(custom_df["ds"])
        # lower_window/upper_window: days before/after the holiday that are affected
        if "lower_window" not in custom_df.columns:
            custom_df["lower_window"] = -1  # 1 day before
        if "upper_window" not in custom_df.columns:
            custom_df["upper_window"] = 1  # 1 day after
        model.holidays = (
            pd.concat([model.holidays, custom_df])
            if model.holidays is not None
            else custom_df
        )
        print(f"  ✓ Added {len(custom_holidays)} custom holidays")

    # ---- Fit the model ----
    print("  Training Prophet model...")
    model.fit(df)
    print("  ✓ Model trained successfully")

    # ---- Generate future predictions ----
    future = model.make_future_dataframe(periods=horizon_days)

    # If using weather regressors, we need weather data for the future period too
    if has_weather:
        last_date = df["ds"].max()
        future_start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        future_end = (last_date + timedelta(days=horizon_days)).strftime("%Y-%m-%d")

        # Try to get actual forecast weather (up to 16 days)
        forecast_weather = fetch_forecast_weather(
            future_start, future_end, latitude, longitude
        )

        # For dates beyond the 16-day forecast, use historical averages
        # by day-of-year as a reasonable approximation
        if weather_data is not None and not weather_data.empty:
            weather_data_copy = weather_data.copy()
            weather_data_copy["day_of_year"] = weather_data_copy["ds"].dt.dayofyear
            seasonal_avg = (
                weather_data_copy.groupby("day_of_year")
                .agg(
                    {
                        "temperature": "mean",
                        "precipitation": "mean",
                    }
                )
                .reset_index()
            )

            # Build weather for all future dates
            future_weather = pd.DataFrame({"ds": future["ds"]})
            future_weather["day_of_year"] = future_weather["ds"].dt.dayofyear
            future_weather = future_weather.merge(
                seasonal_avg, on="day_of_year", how="left"
            )
            future_weather["temperature"] = future_weather["temperature"].ffill().bfill()
            future_weather["precipitation"] = future_weather["precipitation"].ffill().bfill()

            # Override with actual forecast where available
            if forecast_weather is not None:
                for _, row in forecast_weather.iterrows():
                    mask = future_weather["ds"] == row["ds"]
                    if mask.any():
                        future_weather.loc[mask, "temperature"] = row["temperature"]
                        future_weather.loc[mask, "precipitation"] = row["precipitation"]

            # Merge weather into the future dataframe
            future = future.merge(
                future_weather[["ds", "temperature", "precipitation"]],
                on="ds",
                how="left",
            )
            # Also merge historical weather for the historical portion
            hist_weather = df[["ds", "temperature", "precipitation"]].copy()
            for col in ["temperature", "precipitation"]:
                future[col] = future[col].fillna(
                    future["ds"].map(hist_weather.set_index("ds")[col])
                )
            future["temperature"] = future["temperature"].ffill().bfill()
            future["precipitation"] = future["precipitation"].ffill().bfill()
            print(f"  ✓ Added weather data for {horizon_days}-day forecast period")

    if external_regressors is not None and not external_regressors.empty:
        regressor_columns = [c for c in external_regressors.columns if c != "ds"]
        future = future.merge(external_regressors, on="ds", how="left")
        missing_regressor_values = int(future[regressor_columns].isna().sum().sum())
        future[regressor_columns] = future[regressor_columns].fillna(0)
        if missing_regressor_values > 0:
            print(
                f"  ⚠ Filled {missing_regressor_values} missing future regressor values with 0"
            )

    forecast = model.predict(future)
    print(f"  ✓ Generated {horizon_days}-day forecast")

    return model, forecast


# ============================================================
# STEP 6: MODEL BACKTESTING & METRICS
# ============================================================


def infer_season_length(aggregation: str) -> int:
    """Return a reasonable seasonal cycle length for baseline models."""
    if aggregation == "weekly":
        return 4
    if aggregation == "monthly":
        return 12
    return 7


def detect_demand_profile(df: pd.DataFrame) -> dict:
    """Classify a demand series using intermittent-demand heuristics.

    Uses the common ADI/CV^2 framework:
    - ADI: average interval between non-zero demand periods
    - CV^2: squared coefficient of variation of non-zero demand sizes

    Typical interpretation:
    - smooth: ADI < 1.32 and CV^2 < 0.49
    - intermittent: ADI >= 1.32 and CV^2 < 0.49
    - erratic: ADI < 1.32 and CV^2 >= 0.49
    - lumpy: ADI >= 1.32 and CV^2 >= 0.49
    """
    values = df["y"].to_numpy(dtype=float)
    total_periods = len(values)
    positive_values = values[values > 0]
    non_zero_periods = int(len(positive_values))
    zero_ratio = float(np.mean(values == 0)) if total_periods > 0 else 1.0

    if non_zero_periods == 0:
        return {
            "classification": "all_zero",
            "adi": None,
            "cv2": None,
            "zeroRatio": round(zero_ratio, 3),
            "nonZeroPeriods": non_zero_periods,
            "totalPeriods": total_periods,
            "recommendedModels": ["naive", "croston_sba"],
        }

    adi = total_periods / non_zero_periods
    pos_mean = float(np.mean(positive_values))
    pos_std = float(np.std(positive_values)) if non_zero_periods > 1 else 0.0
    cv2 = ((pos_std / pos_mean) ** 2) if pos_mean > 0 else 0.0

    if adi >= 1.32 and cv2 >= 0.49:
        classification = "lumpy"
        recommended = ["croston_sba", "naive", "prophet"]
    elif adi >= 1.32:
        classification = "intermittent"
        recommended = ["croston_sba", "naive", "prophet"]
    elif cv2 >= 0.49:
        classification = "erratic"
        recommended = ["prophet", "naive", "seasonal_naive"]
    else:
        classification = "smooth"
        recommended = ["prophet", "seasonal_naive", "naive"]

    return {
        "classification": classification,
        "adi": round(float(adi), 3),
        "cv2": round(float(cv2), 3),
        "zeroRatio": round(zero_ratio, 3),
        "nonZeroPeriods": non_zero_periods,
        "totalPeriods": total_periods,
        "recommendedModels": recommended,
    }


def summarize_demand_profile(demand_profile: dict) -> str:
    """Create a plain-English summary of the detected demand pattern."""
    classification = demand_profile.get("classification", "unknown")
    adi = demand_profile.get("adi")
    cv2 = demand_profile.get("cv2")
    zero_ratio = demand_profile.get("zeroRatio")

    if classification == "all_zero":
        return (
            "This product has no non-zero sales in the available history, so the pipeline "
            "treats it as an all-zero series and favors simple intermittent baselines."
        )
    if classification == "smooth":
        return (
            f"This product sells fairly regularly with stable order sizes. "
            f"ADI={adi}, CV²={cv2}, zero-ratio={zero_ratio}. "
            "That makes seasonality-aware models like Prophet a good default choice."
        )
    if classification == "erratic":
        return (
            f"This product sells often, but the order sizes jump around a lot. "
            f"ADI={adi}, CV²={cv2}, zero-ratio={zero_ratio}. "
            "The pipeline keeps Prophet in the mix but also compares simpler baselines in case the series is too noisy."
        )
    if classification == "intermittent":
        return (
            f"This product has many zero-sale periods, but when it sells, the order sizes are relatively consistent. "
            f"ADI={adi}, CV²={cv2}, zero-ratio={zero_ratio}. "
            "That is classic intermittent demand, so Croston-style models are tested first."
        )
    if classification == "lumpy":
        return (
            f"This product has many zero-sale periods and the non-zero sales vary a lot in size. "
            f"ADI={adi}, CV²={cv2}, zero-ratio={zero_ratio}. "
            "That is lumpy demand, so the pipeline prioritizes intermittent-demand baselines before Prophet."
        )
    return "The pipeline could not clearly classify this demand pattern."


def summarize_model_selection(
    selected_model: str,
    selection_metric: str,
    comparison_rows: list[dict],
    demand_profile: dict,
    selection_details: dict | None = None,
) -> str:
    """Create a plain-English explanation of why a model was selected."""
    winner = next(
        (row for row in comparison_rows if row.get("model") == selected_model), None
    )
    if not winner:
        return (
            f"The pipeline used {selected_model} because it was the configured model."
        )

    metric_name = winner.get("selection_metric_used", selection_metric)
    metric_value = winner.get(metric_name)
    ordered = [row for row in comparison_rows if row.get(metric_name) is not None]
    ordered.sort(key=lambda row: row[metric_name])
    ranking = ", ".join(
        f"{row['model']} ({metric_name}={row[metric_name]})" for row in ordered
    )

    stability_label = winner.get("stability_label")
    stability_suffix = (
        f" Fold-to-fold performance looked {stability_label.replace('_', ' ')}."
        if stability_label
        else ""
    )
    margin_suffix = ""
    fallback_suffix = ""

    if selection_details:
        runner_up = selection_details.get("runner_up_model")
        margin_abs = selection_details.get("winner_margin_abs")
        margin_pct = selection_details.get("winner_margin_pct")
        requested_metric = selection_details.get("selection_metric_requested")
        used_metric = selection_details.get("selection_metric_used", metric_name)

        if requested_metric and used_metric and requested_metric != used_metric:
            fallback_suffix = f" Requested metric '{requested_metric}' was unavailable, so '{used_metric}' was used."

        if runner_up and margin_abs is not None:
            margin_suffix = f" It beat {runner_up} by {margin_abs} {metric_name} points"
            margin_suffix += f" ({margin_pct}%)." if margin_pct is not None else "."
        elif selection_details.get("valid_candidate_count", 0) <= 1:
            margin_suffix = (
                " Only one candidate produced a valid score for this selection metric."
            )

    return (
        f"The pipeline classified this product as {demand_profile.get('classification', 'unknown')} demand and compared "
        f"{len(ordered)} candidate models. {selected_model} won because it had the lowest {metric_name} "
        f"score ({metric_value}) on the rolling backtests. Ranking: {ranking}."
        f"{margin_suffix}{stability_suffix}{fallback_suffix}"
    )


def resolve_candidate_models(
    requested_models: list[str] | None,
    demand_profile: dict,
) -> list[str]:
    """Resolve candidate models from explicit config or automatic detection."""
    if not requested_models:
        return demand_profile["recommendedModels"]

    normalized = [model.strip() for model in requested_models if model.strip()]
    if not normalized or normalized == ["auto"]:
        return demand_profile["recommendedModels"]

    return normalized


def resolve_selection_metric(
    requested_metric: str | None,
    demand_profile: dict,
) -> str:
    """Choose a user-friendly default selection metric based on demand shape."""
    if requested_metric and requested_metric != "auto":
        return requested_metric

    classification = demand_profile.get("classification")
    if classification in {"intermittent", "lumpy", "all_zero"}:
        return "mase"
    return "wape"


def determine_cv_config(
    df: pd.DataFrame,
    initial_days: int | None = None,
    horizon_days: int | None = None,
    period_days: int | None = None,
) -> dict:
    """Build rolling-origin backtest settings, allowing user overrides."""
    data_days = (df["ds"].max() - df["ds"].min()).days

    default_initial = max(90, int(data_days * 0.6))
    default_horizon = min(30, max(7, int(data_days * 0.2)))
    default_period = default_horizon

    if data_days < 180:
        default_initial = max(60, int(data_days * 0.5))
        default_horizon = min(14, max(7, int(data_days * 0.15)))
        default_period = default_horizon

    config = {
        "initial_days": initial_days or default_initial,
        "horizon_days": horizon_days or default_horizon,
        "period_days": period_days or default_period,
    }

    if config["initial_days"] + config["horizon_days"] >= data_days:
        config["initial_days"] = max(30, data_days - config["horizon_days"] - 1)

    return config


def generate_backtest_folds(
    df: pd.DataFrame, cv_config: dict
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Generate rolling-origin train/test cutoff dates for model comparison."""
    start_date = df["ds"].min()
    end_date = df["ds"].max()
    cutoff = start_date + timedelta(days=cv_config["initial_days"])
    last_cutoff = end_date - timedelta(days=cv_config["horizon_days"])
    folds = []

    while cutoff <= last_cutoff:
        folds.append((cutoff, cutoff + timedelta(days=cv_config["horizon_days"])))
        cutoff += timedelta(days=cv_config["period_days"])

    if not folds and cv_config["horizon_days"] < (end_date - start_date).days:
        cutoff = end_date - timedelta(days=cv_config["horizon_days"])
        folds.append((cutoff, end_date))

    return folds


def compute_error_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, insample_values: np.ndarray
) -> dict:
    """Compute shared forecast quality metrics for all models."""
    abs_error = np.abs(y_true - y_pred)
    squared_error = (y_true - y_pred) ** 2
    non_zero_mask = y_true != 0
    wape_denominator = np.abs(y_true).sum()
    smape_denominator = np.abs(y_true) + np.abs(y_pred)
    naive_diffs = np.abs(np.diff(insample_values))
    mase_denominator = naive_diffs.mean() if len(naive_diffs) > 0 else 0

    mape = (
        float(np.mean(abs_error[non_zero_mask] / np.abs(y_true[non_zero_mask]))) * 100
        if non_zero_mask.any()
        else None
    )

    smape_terms = np.zeros_like(abs_error, dtype=float)
    np.divide(
        2 * abs_error,
        smape_denominator,
        out=smape_terms,
        where=smape_denominator != 0,
    )

    mean_abs_error = float(np.mean(abs_error)) if len(abs_error) > 0 else 0.0

    result = {
        "mape": round(mape, 2) if mape is not None else None,
        "wape": (
            round(float(abs_error.sum() / wape_denominator) * 100, 2)
            if wape_denominator > 0
            else None
        ),
        "smape": round(float(np.mean(smape_terms)) * 100, 2),
        "mase": (
            round(float(mean_abs_error / mase_denominator), 3)
            if mase_denominator > 0
            else (0.0 if mean_abs_error == 0 else None)
        ),
        "rmse": round(float(np.sqrt(np.mean(squared_error))), 2),
        "mae": round(mean_abs_error, 2),
    }

    if result["mape"] is None:
        result["mape_rating"] = "Unknown"
        result["mape_color"] = "gray"
    elif result["mape"] < 15:
        result["mape_rating"] = "Excellent"
        result["mape_color"] = "green"
    elif result["mape"] < 30:
        result["mape_rating"] = "Good"
        result["mape_color"] = "yellow"
    else:
        result["mape_rating"] = "Poor"
        result["mape_color"] = "red"

    return result


def build_baseline_forecast(
    model_name: str,
    train_values: np.ndarray,
    horizon: int,
    season_length: int,
) -> np.ndarray:
    """Produce baseline forecasts for non-Prophet candidate models."""
    if len(train_values) == 0:
        return np.zeros(horizon, dtype=float)

    if model_name == "naive":
        return np.repeat(train_values[-1], horizon).astype(float)

    if model_name == "seasonal_naive":
        if len(train_values) < season_length:
            return np.repeat(train_values[-1], horizon).astype(float)
        template = train_values[-season_length:]
        return np.array(
            [template[i % season_length] for i in range(horizon)], dtype=float
        )

    if model_name == "croston_sba":
        positive_indices = np.where(train_values > 0)[0]
        if len(positive_indices) == 0:
            return np.zeros(horizon, dtype=float)

        alpha = 0.1
        first_idx = int(positive_indices[0])
        demand_estimate = train_values[first_idx]
        interval_estimate = 1.0
        interval = 1.0

        for value in train_values[first_idx + 1 :]:
            if value > 0:
                demand_estimate = demand_estimate + alpha * (value - demand_estimate)
                interval_estimate = interval_estimate + alpha * (
                    interval - interval_estimate
                )
                interval = 1.0
            else:
                interval += 1.0

        croston_rate = (1 - alpha / 2) * demand_estimate / max(interval_estimate, 1e-9)
        return np.repeat(max(0.0, croston_rate), horizon).astype(float)

    raise ValueError(f"Unsupported baseline model: {model_name}")


def build_baseline_forecast_frame(
    df: pd.DataFrame,
    model_name: str,
    horizon_days: int,
    aggregation: str,
) -> tuple[dict, pd.DataFrame]:
    """Train a baseline model on the full history and produce future rows."""
    future_dates = pd.date_range(
        start=df["ds"].max() + pd.Timedelta(days=1),
        periods=horizon_days,
        freq="D",
    )
    season_length = infer_season_length(aggregation)
    preds = build_baseline_forecast(
        model_name, df["y"].to_numpy(dtype=float), horizon_days, season_length
    )
    residual_scale = float(df["y"].std()) if len(df) > 1 else 0.0

    forecast = pd.DataFrame(
        {
            "ds": future_dates,
            "yhat": preds,
            "yhat_lower": np.maximum(0, preds - 1.96 * residual_scale),
            "yhat_upper": preds + 1.96 * residual_scale,
        }
    )
    return {"model_name": model_name}, forecast


def backtest_single_model(
    model_name: str,
    df: pd.DataFrame,
    aggregation: str,
    cv_config: dict,
    country: str | None = None,
    custom_holidays: list[dict] | None = None,
    tuned_params: dict | None = None,
) -> dict:
    """Run rolling backtests for a single candidate model."""
    regressor_columns = [c for c in df.columns if c not in {"ds", "y"}]
    season_length = infer_season_length(aggregation)
    y_true_all = []
    y_pred_all = []
    fold_metrics = []
    folds = generate_backtest_folds(df, cv_config)

    if not folds:
        raise ValueError(
            "Unable to generate backtest folds with the current CV settings"
        )

    for cutoff, horizon_end in folds:
        train_df = df[df["ds"] <= cutoff].copy()
        test_df = df[(df["ds"] > cutoff) & (df["ds"] <= horizon_end)].copy()
        if test_df.empty:
            continue

        if model_name == "prophet":
            avg_sales = train_df["y"].mean()
            std_sales = train_df["y"].std()
            cv_value = std_sales / avg_sales if avg_sales > 0 else 0
            seasonality_mode = "multiplicative" if cv_value > 0.5 else "additive"
            cps = (
                tuned_params.get("changepoint_prior_scale", 0.1)
                if tuned_params
                else 0.1
            )
            sps = (
                tuned_params.get("seasonality_prior_scale", 10.0)
                if tuned_params
                else 10.0
            )
            monthly_fourier = (
                tuned_params.get("monthly_fourier_order", 5) if tuned_params else 5
            )
            seasonality_mode = (
                tuned_params.get("seasonality_mode", seasonality_mode)
                if tuned_params
                else seasonality_mode
            )

            model = Prophet(
                changepoint_prior_scale=cps,
                seasonality_prior_scale=sps,
                seasonality_mode=seasonality_mode,
                interval_width=0.95,
                daily_seasonality=False,
                weekly_seasonality=True,
                yearly_seasonality=True,
            )
            model.add_seasonality(
                name="monthly", period=30.5, fourier_order=monthly_fourier
            )
            for col in regressor_columns:
                model.add_regressor(col)
            if country:
                model.add_country_holidays(country_name=country)
            if custom_holidays:
                model.holidays = pd.DataFrame(custom_holidays)

            model.fit(train_df)
            future = model.make_future_dataframe(periods=len(test_df), freq="D")
            if regressor_columns:
                known_regressors = pd.concat(
                    [
                        train_df[["ds", *regressor_columns]],
                        test_df[["ds", *regressor_columns]],
                    ]
                ).drop_duplicates(subset=["ds"], keep="last")
                future = future.merge(known_regressors, on="ds", how="left")
                future[regressor_columns] = (
                    future[regressor_columns].ffill().bfill().fillna(0)
                )
            forecast = model.predict(future)
            preds = (
                forecast.tail(len(test_df))["yhat"].clip(lower=0).to_numpy(dtype=float)
            )
        else:
            preds = build_baseline_forecast(
                model_name,
                train_df["y"].to_numpy(dtype=float),
                len(test_df),
                season_length,
            )

        y_true_all.extend(test_df["y"].to_numpy(dtype=float))
        y_pred_all.extend(preds)

        fold_metric = compute_error_metrics(
            test_df["y"].to_numpy(dtype=float),
            np.array(preds, dtype=float),
            train_df["y"].to_numpy(dtype=float),
        )
        fold_metrics.append(
            {
                "cutoff": cutoff.strftime("%Y-%m-%d"),
                "horizonEnd": horizon_end.strftime("%Y-%m-%d"),
                **fold_metric,
            }
        )

    metrics = compute_error_metrics(
        np.array(y_true_all, dtype=float),
        np.array(y_pred_all, dtype=float),
        df["y"].to_numpy(dtype=float),
    )
    metrics["model"] = model_name
    metrics["folds"] = len(folds)
    metrics["_fold_metrics"] = fold_metrics
    return metrics


def compute_selection_stability(fold_metrics: list[dict], metric_name: str) -> dict:
    """Summarize fold-to-fold variability for the metric used in model selection."""
    values = []
    for row in fold_metrics or []:
        value = row.get(metric_name)
        if value is None:
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(numeric_value):
            values.append(numeric_value)

    if not values:
        return {
            "mean": None,
            "std": None,
            "cv": None,
            "label": "insufficient_folds",
            "count": 0,
        }

    arr = np.array(values, dtype=float)
    mean_val = float(np.mean(arr))
    std_val = float(np.std(arr))
    cv_val = abs(std_val / mean_val) if mean_val != 0 else None

    if len(values) < 3:
        label = "insufficient_folds"
    elif cv_val is None:
        label = "stable" if std_val == 0 else "volatile"
    elif cv_val <= 0.10:
        label = "stable"
    elif cv_val <= 0.25:
        label = "moderate"
    else:
        label = "volatile"

    return {
        "mean": round(mean_val, 3),
        "std": round(std_val, 3),
        "cv": round(cv_val, 3) if cv_val is not None else None,
        "label": label,
        "count": len(values),
    }


def backtest_candidate_models(
    df: pd.DataFrame,
    aggregation: str,
    candidate_models: list[str],
    selection_metric: str,
    cv_config: dict,
    country: str | None = None,
    custom_holidays: list[dict] | None = None,
    tuned_params: dict | None = None,
) -> tuple[dict, list[dict], dict]:
    """Backtest all requested candidates and return the best one plus comparison rows."""
    fallback_metric_order = [
        selection_metric,
        "mase",
        "mae",
        "rmse",
        "smape",
        "wape",
        "mape",
    ]
    results = []
    for model_name in candidate_models:
        metrics = backtest_single_model(
            model_name,
            df,
            aggregation,
            cv_config,
            country=country,
            custom_holidays=custom_holidays,
            tuned_params=tuned_params if model_name == "prophet" else None,
        )
        results.append(metrics)

    chosen_metric = None
    valid_results = []
    for metric_name in fallback_metric_order:
        valid_results = [r for r in results if r.get(metric_name) is not None]
        if valid_results:
            chosen_metric = metric_name
            break

    if not valid_results or chosen_metric is None:
        raise ValueError(
            f"No candidate produced a valid score for selection. Tried: {fallback_metric_order}"
        )

    # Deterministic tie-breaking: Prophet > Croston > Seasonal Naive > Naive > others
    model_priority = [
        "prophet",
        "croston_sba",
        "seasonal_naive",
        "naive",
    ]
    # Find the best score(s)
    ordered_valid = sorted(valid_results, key=lambda row: row[chosen_metric])
    best_score = ordered_valid[0][chosen_metric]
    tied = [row for row in ordered_valid if row[chosen_metric] == best_score]
    if len(tied) > 1:
        # Sort tied models by priority, then by name for stability
        def tie_break_key(row):
            try:
                return (model_priority.index(row["model"]), row["model"])
            except ValueError:
                return (len(model_priority), row["model"])

        tied = sorted(tied, key=tie_break_key)
    best = tied[0]
    # Find runner-up (next best, not the same model)
    runner_up = None
    for row in ordered_valid:
        if row["model"] != best["model"]:
            runner_up = row
            break

    winner_score = best.get(chosen_metric)
    runner_score = runner_up.get(chosen_metric) if runner_up else None
    winner_margin_abs = None
    winner_margin_pct = None
    winner_is_clear = None
    if runner_up and runner_score is not None and winner_score is not None:
        winner_margin_abs = round(float(runner_score - winner_score), 3)
        if runner_score != 0:
            winner_margin_pct = round(
                float((winner_margin_abs / abs(runner_score)) * 100), 2
            )
        if winner_margin_pct is not None:
            winner_is_clear = winner_margin_pct >= 5

    best["selection_metric_used"] = chosen_metric
    for row in results:
        row["selection_metric_used"] = chosen_metric
        stability = compute_selection_stability(
            row.pop("_fold_metrics", []), chosen_metric
        )
        row["selection_metric_mean"] = stability["mean"]
        row["selection_metric_std"] = stability["std"]
        row["selection_metric_cv"] = stability["cv"]
        row["stability_label"] = stability["label"]
        row["valid_fold_scores"] = stability["count"]

    selection_details = {
        "selection_metric_requested": selection_metric,
        "selection_metric_used": chosen_metric,
        "candidate_count": len(results),
        "valid_candidate_count": len(ordered_valid),
        "winner_model": best.get("model"),
        "winner_score": winner_score,
        "runner_up_model": runner_up.get("model") if runner_up else None,
        "runner_up_score": runner_score,
        "winner_margin_abs": winner_margin_abs,
        "winner_margin_pct": winner_margin_pct,
        "winner_is_clear": winner_is_clear,
        "selection_fallback_applied": chosen_metric != selection_metric,
    }

    return best, results, selection_details


# NOTE: calculate_metrics() was removed — the pipeline now uses
# backtest_candidate_models() + backtest_single_model() for all
# rolling-origin cross-validation. prophet.diagnostics.cross_validation
# is still used inside tune_hyperparameters() for Optuna trials only.


def load_custom_holidays(
    file_path: str | None,
    date_col: str = "ds",
    name_col: str = "holiday",
    product_col: str | None = None,
    lower_window_col: str | None = None,
    upper_window_col: str | None = None,
) -> pd.DataFrame | None:
    """Load optional user-provided holidays/events from CSV."""
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        print(f"  ✗ Holidays file not found: {path.resolve()}")
        sys.exit(1)

    holidays_df = pd.read_csv(path)
    missing = [col for col in [date_col, name_col] if col not in holidays_df.columns]
    if missing:
        print(f"  ✗ Holidays file missing required columns: {missing}")
        sys.exit(1)

    rename_map = {date_col: "ds", name_col: "holiday"}
    if product_col and product_col in holidays_df.columns:
        rename_map[product_col] = "product_id"

    holidays_df = holidays_df.rename(columns=rename_map)
    holidays_df["ds"] = pd.to_datetime(holidays_df["ds"], errors="coerce")
    holidays_df = holidays_df.dropna(subset=["ds", "holiday"]).copy()

    if "product_id" in holidays_df.columns:
        holidays_df["product_id"] = holidays_df["product_id"].astype(str).str.strip()
        holidays_df.loc[holidays_df["product_id"] == "", "product_id"] = np.nan

    holidays_df["lower_window"] = 0
    holidays_df["upper_window"] = 0
    if lower_window_col and lower_window_col in holidays_df.columns:
        holidays_df["lower_window"] = (
            pd.to_numeric(holidays_df[lower_window_col], errors="coerce")
            .fillna(0)
            .astype(int)
        )
    if upper_window_col and upper_window_col in holidays_df.columns:
        holidays_df["upper_window"] = (
            pd.to_numeric(holidays_df[upper_window_col], errors="coerce")
            .fillna(0)
            .astype(int)
        )

    keep_columns = ["holiday", "ds", "lower_window", "upper_window"]
    if "product_id" in holidays_df.columns:
        keep_columns.append("product_id")

    holidays_df = holidays_df[keep_columns].drop_duplicates().reset_index(drop=True)
    print(f"  ✓ Loaded {len(holidays_df)} custom holiday/event row(s) from {path.name}")
    return holidays_df


def select_product_holidays(
    holidays_df: pd.DataFrame | None,
    product_id: str,
) -> list[dict] | None:
    """Return global + product-specific holidays for one product."""
    if holidays_df is None or holidays_df.empty:
        return None

    selected = holidays_df.copy()
    if "product_id" in selected.columns:
        selected = selected[
            (selected["product_id"].isna())
            | (selected["product_id"] == str(product_id))
        ]

    if selected.empty:
        return None

    return selected[["holiday", "ds", "lower_window", "upper_window"]].to_dict(
        "records"
    )


def load_external_regressors(
    file_path: str | None,
    date_col: str = "date",
    product_col: str | None = None,
    regressor_columns: list[str] | None = None,
) -> pd.DataFrame | None:
    """Load optional user-provided regressor data from CSV."""
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        print(f"  ✗ Regressors file not found: {path.resolve()}")
        sys.exit(1)

    reg_df = pd.read_csv(path)
    if date_col not in reg_df.columns:
        print(f"  ✗ Regressors file missing required date column: {date_col}")
        sys.exit(1)

    rename_map = {date_col: "ds"}
    if product_col and product_col in reg_df.columns:
        rename_map[product_col] = "product_id"
    reg_df = reg_df.rename(columns=rename_map)

    reg_df["ds"] = pd.to_datetime(reg_df["ds"], errors="coerce")
    reg_df = reg_df.dropna(subset=["ds"]).copy()

    if "product_id" in reg_df.columns:
        reg_df["product_id"] = reg_df["product_id"].astype(str)

    inferred_columns = [c for c in reg_df.columns if c not in {"ds", "product_id"}]
    selected_columns = regressor_columns or inferred_columns
    missing_columns = [c for c in selected_columns if c not in reg_df.columns]
    if missing_columns:
        print(f"  ✗ Regressors file missing requested columns: {missing_columns}")
        sys.exit(1)

    if not selected_columns:
        print("  ✗ No regressor columns found. Add columns or pass --regressor-cols.")
        sys.exit(1)

    for col in selected_columns:
        reg_df[col] = pd.to_numeric(reg_df[col], errors="coerce").fillna(0)

    keep_columns = ["ds", *selected_columns]
    if "product_id" in reg_df.columns:
        keep_columns.insert(1, "product_id")

    dedupe_columns = ["ds"] + (["product_id"] if "product_id" in reg_df.columns else [])
    reg_df = reg_df[keep_columns].drop_duplicates(subset=dedupe_columns, keep="last")
    print(f"  ✓ Loaded regressors from {path.name}: {', '.join(selected_columns)}")
    return reg_df.reset_index(drop=True)


def select_product_regressors(
    regressor_df: pd.DataFrame | None,
    product_id: str,
) -> pd.DataFrame | None:
    """Return product-specific or global regressor rows for one product."""
    if regressor_df is None or regressor_df.empty:
        return None

    selected = regressor_df.copy()
    if "product_id" in selected.columns:
        selected = selected[selected["product_id"] == str(product_id)]
    if selected.empty:
        return None

    if "product_id" in selected.columns:
        selected = selected.drop(columns=["product_id"])

    return selected.sort_values("ds").reset_index(drop=True)


# ============================================================
# STEP 6.5: TREND CHANGE DETECTION
# ============================================================


def detect_trend_changes(model: Prophet, forecast: pd.DataFrame) -> list[dict]:
    """
    Extract and analyze Prophet's detected trend changepoints.

    Prophet automatically identifies dates where the growth rate
    (trend slope) changed significantly. This function extracts
    those dates and calculates the magnitude of each change,
    helping users understand when and how their sales trajectory
    shifted.

    Returns:
        List of dicts with date, direction, magnitude, description
    """
    changes = []

    try:
        if not hasattr(model, "changepoints") or model.changepoints is None:
            return changes

        changepoint_dates = model.changepoints
        if len(changepoint_dates) == 0:
            return changes

        # Get the slope changes at each changepoint
        deltas = model.params["delta"].mean(axis=0)

        # Get the trend values to compute context
        trend = forecast[["ds", "trend"]].copy()

        for i, (cp_date, delta) in enumerate(zip(changepoint_dates, deltas)):
            delta_val = float(delta)

            # Only report significant changes (> 0.5 units/day slope shift)
            if abs(delta_val) < 0.5:
                continue

            direction = "up" if delta_val > 0 else "down"

            # Find the trend value at this changepoint for context
            closest_idx = (trend["ds"] - cp_date).abs().idxmin()
            trend_at_point = float(trend.loc[closest_idx, "trend"])

            changes.append(
                {
                    "date": cp_date.strftime("%Y-%m-%d"),
                    "direction": direction,
                    "magnitude": round(abs(delta_val), 2),
                    "trendAtChange": round(trend_at_point, 1),
                    "description": (
                        f"Trend {'increased' if direction == 'up' else 'decreased'} "
                        f"by {abs(delta_val):.1f} units/day"
                    ),
                }
            )

        # Sort by magnitude (most impactful first)
        changes.sort(key=lambda x: x["magnitude"], reverse=True)

    except Exception as e:
        print(f"  Warning: Could not extract trend changes: {e}")

    return changes


# ============================================================
# STEP 7: FORMAT RESULTS FOR FRONTEND
# ============================================================


def format_frontend_data(
    df: pd.DataFrame,
    forecast: pd.DataFrame,
    model: Prophet,
    metrics: dict,
    product_id: str,
    product_name: str,
) -> dict:
    """
    Shape all results into the JSON structure the frontend needs
    for rendering interactive charts.

    The frontend renders charts using a JS library (e.g., Recharts).
    The backend's job is to send clean, structured data — NOT images.

    Output structure:
    {
        "historical": [...],    → Line chart of past sales
        "forecast": [...],      → Line chart + confidence band
        "components": {...},    → Trend, weekly, yearly bar/line charts
        "metrics": {...},       → MAPE gauge, stats cards
    }
    """
    # Split forecast into historical (fitted) and future periods
    last_historical_date = df["ds"].max()

    # Historical data points (actual sales)
    historical = []
    for _, row in df.iterrows():
        historical.append(
            {
                "date": row["ds"].strftime("%Y-%m-%d"),
                "actual": round(float(row["y"]), 1),
            }
        )

    # Forecast data points (predicted + confidence intervals)
    forecast_data = []
    future_rows = forecast[forecast["ds"] > last_historical_date]
    for _, row in future_rows.iterrows():
        forecast_data.append(
            {
                "date": row["ds"].strftime("%Y-%m-%d"),
                "predicted": round(float(row["yhat"]), 1),
                # Lower and upper bounds of the 95% confidence interval
                "lowerBound": round(float(max(0, row["yhat_lower"])), 1),
                "upperBound": round(float(row["yhat_upper"]), 1),
            }
        )

    # Component decomposition (for trend/seasonality charts)
    # Trend over the full period (historical + forecast)
    trend_data = []
    if "trend" in forecast.columns:
        for _, row in forecast.iterrows():
            trend_data.append(
                {
                    "date": row["ds"].strftime("%Y-%m-%d"),
                    "value": round(float(row["trend"]), 1),
                }
            )

    # Weekly seasonality (average effect per day of week)
    weekly_data = []
    if "weekly" in forecast.columns:
        forecast_copy = forecast.copy()
        forecast_copy["dow"] = forecast_copy["ds"].dt.day_name()
        weekly_avg = forecast_copy.groupby("dow")["weekly"].mean()
        day_order = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        for day in day_order:
            if day in weekly_avg.index:
                weekly_data.append(
                    {
                        "dayOfWeek": day,
                        "effect": round(float(weekly_avg[day]), 2),
                    }
                )

    # Yearly seasonality (average effect per month)
    yearly_data = []
    if "yearly" in forecast.columns:
        forecast_copy = forecast.copy()
        forecast_copy["month"] = forecast_copy["ds"].dt.month_name()
        yearly_avg = forecast_copy.groupby(forecast_copy["ds"].dt.month)[
            "yearly"
        ].mean()
        import calendar

        for month_num, effect in yearly_avg.items():
            yearly_data.append(
                {
                    "month": calendar.month_name[month_num],
                    "effect": round(float(effect), 2),
                }
            )

    result = {
        "productId": product_id,
        "productName": product_name,
        "generatedAt": datetime.now().isoformat(),
        "historical": historical,
        "forecast": forecast_data,
        "components": {
            "trend": trend_data,
            "weekly": weekly_data,
            "yearly": yearly_data,
        },
        "metrics": metrics,
    }

    return result


# ============================================================
# STEP 8: GEMINI AI EXPLANATION
# ============================================================


def generate_gemini_explanation(
    frontend_data: dict,
    model_name: str = "gemini-3.1-flash-lite-preview",
) -> str | None:
    """
    Send forecast context to Gemini and get a plain-English explanation.

    The explanation is structured for NON-TECHNICAL business users.
    No jargon, no statistics terms — just clear, actionable insights.

    The prompt asks Gemini to produce 6 sections:
    1. Overview — What the forecast says in 1-2 sentences
    2. What the Data Shows — Patterns found, explained simply
    3. How Reliable Is This Forecast — Accuracy in plain language
    4. Actionable Recommendations — 3-5 specific inventory actions
    5. Risks to Watch — Factors that could change things
    6. What to Do Next — Clear next steps

    Args:
        frontend_data: The structured forecast data from format_frontend_data()
        model_name: Which Gemini model to use

    Returns:
        The AI-generated explanation string, or None if unavailable
    """
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key or api_key == "your-gemini-api-key-here":
        print("  ⚠ GEMINI_API_KEY not set in .env — skipping AI explanation")
        print("    To enable: add your API key to backend/.env")
        return None

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
    except ImportError:
        print("  ⚠ google-genai not installed — skipping AI explanation")
        print("    Run: pip install google-genai")
        return None

    # ---- Build context from forecast data ----
    metrics = frontend_data["metrics"]
    historical = frontend_data["historical"]
    forecast = frontend_data["forecast"]
    components = frontend_data["components"]
    demand_profile = frontend_data.get("demandProfile", {})
    model_selection = frontend_data.get("modelSelection", {})
    selected_model = frontend_data.get("selectedModel", "prophet")

    # Calculate summary statistics for the prompt
    hist_values = [h["actual"] for h in historical]
    forecast_values = [f["predicted"] for f in forecast]
    lower_bounds = [f["lowerBound"] for f in forecast]
    upper_bounds = [f["upperBound"] for f in forecast]

    avg_historical = sum(hist_values) / len(hist_values) if hist_values else 0
    avg_forecast = sum(forecast_values) / len(forecast_values) if forecast_values else 0
    total_forecast_volume = sum(forecast_values)
    total_lower_bound = sum(lower_bounds)
    total_upper_bound = sum(upper_bounds)
    growth_pct = (
        ((avg_forecast - avg_historical) / avg_historical * 100)
        if avg_historical > 0
        else 0
    )

    # Pre-compute plain-language confidence band (±units per day)
    mape_val = metrics.get("mape", 0)
    confidence_units = (
        round(avg_historical * (mape_val / 100), 1) if avg_historical > 0 else 0
    )
    confidence_band_text = (
        f"On a typical day selling ~{avg_historical:.0f} units, "
        f"this forecast could be off by about ±{confidence_units} units."
    )

    # Compute last-30-days vs prior-30-days momentum
    if len(hist_values) >= 60:
        last_30 = hist_values[-30:]
        prior_30 = hist_values[-60:-30]
        avg_last_30 = sum(last_30) / len(last_30)
        avg_prior_30 = sum(prior_30) / len(prior_30)
        momentum_pct = (
            ((avg_last_30 - avg_prior_30) / avg_prior_30 * 100)
            if avg_prior_30 > 0
            else 0
        )
        if momentum_pct > 1:
            momentum_text = f"Sales over the last 30 days averaged {avg_last_30:.1f} units/day, up {momentum_pct:+.1f}% compared to the prior 30 days ({avg_prior_30:.1f} units/day). The trend is currently accelerating."
        elif momentum_pct < -1:
            momentum_text = f"Sales over the last 30 days averaged {avg_last_30:.1f} units/day, down {momentum_pct:+.1f}% compared to the prior 30 days ({avg_prior_30:.1f} units/day). The trend is currently cooling off."
        else:
            momentum_text = f"Sales over the last 30 days averaged {avg_last_30:.1f} units/day, essentially flat compared to the prior 30 days ({avg_prior_30:.1f} units/day)."
    else:
        momentum_text = "Not enough data to compare recent vs prior 30-day performance."

    # Identify peak/low days from weekly seasonality
    weekly = components.get("weekly", [])
    peak_day = max(weekly, key=lambda x: x["effect"])["dayOfWeek"] if weekly else "N/A"
    low_day = min(weekly, key=lambda x: x["effect"])["dayOfWeek"] if weekly else "N/A"

    # Identify peak/low months from yearly seasonality
    yearly = components.get("yearly", [])
    peak_month = max(yearly, key=lambda x: x["effect"])["month"] if yearly else "N/A"
    low_month = min(yearly, key=lambda x: x["effect"])["month"] if yearly else "N/A"

    # Trend changes & Data Health
    trend_changes = frontend_data.get("trendChanges", [])
    trend_changes_text = "\n".join(
        [
            f"- {tc['date']}: Trend {tc['direction']} by {tc['magnitude']} units/day"
            for tc in trend_changes
        ]
    )
    if not trend_changes_text:
        trend_changes_text = "- No major trend shifts detected"

    data_health = frontend_data.get("dataHealth", {})
    health_score = data_health.get("overallScore", "Unknown")
    health_rating = data_health.get("rating", "Unknown")

    # Filter data warnings to only include issues relevant to this product.
    # Global validation issues (not prefixed with a different SKU) are kept.
    current_pid = frontend_data.get("productId", "")
    raw_warnings = data_health.get("warnings", []) + data_health.get("issuesFixed", [])
    filtered_warnings = [
        w for w in raw_warnings if not w.startswith("SKU-") or w.startswith(current_pid)
    ]
    data_warnings_text = "\n".join([f"- {w}" for w in filtered_warnings[:5]])
    if not data_warnings_text:
        data_warnings_text = "- Data is clean, no major issues detected"

    # Determine if weather regressors were used (flag for the prompt).
    # Check the historical data rows — if any row carries a 'temperature' key,
    # weather regressors were merged before training.
    has_weather = (
        len(historical) > 0 and "temperature" in historical[0]
    ) or (
        "regressors" in frontend_data
        and "temperature" in frontend_data.get("regressors", [])
    )

    # ---- Construct the prompt ----
    # Build enriched pattern context with magnitudes.
    # Skip patterns with negligible effects (< 1 unit) to avoid
    # meaningless recommendations like "staff up for 0.09 extra units".
    NEGLIGIBLE_THRESHOLD = 1.0

    if weekly:
        peak_day_obj = max(weekly, key=lambda x: x["effect"])
        low_day_obj = min(weekly, key=lambda x: x["effect"])
        if abs(peak_day_obj["effect"]) >= NEGLIGIBLE_THRESHOLD:
            peak_day_detail = (
                f"{peak_day} ({peak_day_obj['effect']:+.1f} units vs. average)"
            )
        else:
            peak_day_detail = (
                f"{peak_day} (minimal difference — not significant enough to act on)"
            )
        if abs(low_day_obj["effect"]) >= NEGLIGIBLE_THRESHOLD:
            low_day_detail = (
                f"{low_day} ({low_day_obj['effect']:+.1f} units vs. average)"
            )
        else:
            low_day_detail = (
                f"{low_day} (minimal difference — not significant enough to act on)"
            )
    else:
        peak_day_detail = "N/A"
        low_day_detail = "N/A"

    if yearly:
        peak_month_obj = max(yearly, key=lambda x: x["effect"])
        low_month_obj = min(yearly, key=lambda x: x["effect"])
        if abs(peak_month_obj["effect"]) >= NEGLIGIBLE_THRESHOLD:
            peak_month_detail = (
                f"{peak_month} ({peak_month_obj['effect']:+.1f} units vs. average)"
            )
        else:
            peak_month_detail = (
                f"{peak_month} (minimal difference — not significant enough to act on)"
            )
        if abs(low_month_obj["effect"]) >= NEGLIGIBLE_THRESHOLD:
            low_month_detail = (
                f"{low_month} ({low_month_obj['effect']:+.1f} units vs. average)"
            )
        else:
            low_month_detail = (
                f"{low_month} (minimal difference — not significant enough to act on)"
            )
    else:
        peak_month_detail = "N/A"
        low_month_detail = "N/A"

    weather_note = (
        "Weather data (temperature and precipitation) was incorporated as an additional input to this forecast, which generally improves accuracy for weather-sensitive products."
        if has_weather
        else "No weather data was used in this forecast."
    )

    prompt = f"""You are a friendly business advisor helping a small business owner understand their sales forecast.
Imagine you are explaining this to a sari-sari store owner or a small shop owner who wants clear, practical advice.
Write in conversational, everyday language. Speak directly to the business owner using "you" and "your".

LANGUAGE RULES:
- Do NOT open with greetings like "Hi there!", "Hey!", "Hello!", or "Good news!". Jump straight into the insight.
- You may reference underlying numbers and scores to give context (e.g., "your sales records are in good shape, scoring 75 out of 100"), but always LEAD with the plain-English meaning first.
- NEVER use these terms: "baseline", "regressors", "confidence bound", "error rate", "variance", "seasonality", "interpolation", "additive", "multiplicative".
- Instead say: "usual", "normal", "slow scenario", "best-case", "worst-case", "pattern", "trend".
- If a day-of-week pattern is marked as "not significant enough to act on", do NOT recommend staffing or operational changes for that day.
- When citing seasonal patterns, ALWAYS include the magnitude for BOTH the peak AND low period (e.g., "May adds about +6 units per day while November drops about -5 units per day").
- When recommending inventory quantities, add a 10-15% safety buffer above the base projected volume (but do not exceed the best-case number). Explain WHY the buffer is important (e.g., "to avoid running out if sales come in stronger than expected").

Here is the forecast data for their product:

PRODUCT: {frontend_data['productName']} ({frontend_data['productId']})
HISTORICAL PERIOD: {historical[0]['date']} to {historical[-1]['date']} ({len(historical)} days)
FORECAST PERIOD: {forecast[0]['date']} to {forecast[-1]['date']} ({len(forecast)} days)

KEY NUMBERS:
- Average daily sales (past): {avg_historical:.1f} units
- Average daily sales (future): {avg_forecast:.1f} units
- Total projected volume for next {len(forecast)} days: {total_forecast_volume:.0f} units
- Recommended order with ~10% buffer: {min(total_forecast_volume * 1.1, total_upper_bound):.0f} units
- In a slow scenario: {total_lower_bound:.0f} units
- In a best-case scenario: {total_upper_bound:.0f} units
- Expected growth/decline: {growth_pct:+.1f}%

RECENT MOMENTUM:
{momentum_text}

DATA QUALITY & ACCURACY:
- Accuracy in plain terms: {confidence_band_text}
- Data health score: {health_score}/100 ({health_rating})
- Demand type detected: {demand_profile.get('classification', 'unknown')}
- Forecast model used: {selected_model}
- Why this model was used: {model_selection.get('summary', 'No model-selection summary available.')}
- Known Data Issues (for this product only):
{data_warnings_text}
- {weather_note}

PATTERNS FOUND:
- Busiest day of the week: {peak_day_detail}
- Slowest day of the week: {low_day_detail}
- Busiest month of the year: {peak_month_detail}
- Slowest month of the year: {low_month_detail}

RECENT TREND SHIFTS:
{trend_changes_text}

IMPORTANT GUIDELINES:
- In "overview", include the exact total projected volume, the slow/best-case numbers, and a brief mention of recent momentum.
- In "patterns", only highlight patterns that are meaningful (>= 1 unit effect). Always cite the magnitude for BOTH peak AND low. If a weekly pattern is negligible, say so briefly and move on.
- In "reliability", explain confidence in plain terms (e.g., "on a day you'd normally sell about 48 units, the actual number could land anywhere between 40 and 56"). Also mention the data health score with context.
- In "reliability", briefly mention the detected demand type and why the pipeline chose the winning model, but explain it in everyday language.
- In "recommendations", START EACH with an action verb. Include a ~10% buffer on inventory orders. Only recommend operational changes when the pattern is large enough to justify it. Explain WHY each action is beneficial.
- In "risks", ONLY mention risks grounded in the specific data above. Do NOT use generic filler.
- In "nextSteps", give concrete, immediately actionable steps the business owner can take this week.

EXAMPLE OF GOOD OUTPUT (for reference — adapt to the actual data above):
{{
  "overview": "Your Widget sales are on the rise, with a projected total of 5,200 units over the next 90 days. In a slow scenario you would still sell around 4,600 units, and if things go really well, up to 5,800. Recent sales have been climbing at +3% over the past month.",
  "patterns": "Your day-to-day sales are fairly even throughout the week, with no single day standing out enough to change your staffing. The bigger pattern is seasonal: May typically brings in about 6 extra units per day compared to normal, while November dips by about 5 units per day.",
  "reliability": "Your sales records are in solid shape, scoring 78 out of 100 for data quality. On a typical day where you sell around 50 units, the actual number could land anywhere between 43 and 57. That makes this a dependable guide for your ordering decisions.",
  "recommendations": [
    "Order around 5,720 units to cover the projected 5,200 with a 10% safety buffer, so you do not run out if demand comes in stronger than expected.",
    "Place a larger-than-usual restock order by late April to prepare for your May peak, when daily sales typically jump by 6 units above normal."
  ],
  "risks": [
    "About 25 sales entries were missing from your records, which creates small gaps in the data the forecast is built on.",
    "This forecast does not account for weather, so an unusually hot or rainy stretch could push your actual sales above or below these numbers."
  ],
  "nextSteps": [
    "Compare your current stock count against the 5,720-unit order target to figure out how much to reorder this week.",
    "Set an April 15 calendar reminder to place your pre-May bulk order."
  ]
}}
"""

    # ---- Define response schema for structured output ----
    response_schema = {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "patterns": {"type": "string"},
            "reliability": {"type": "string"},
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
            },
            "nextSteps": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "overview",
            "patterns",
            "reliability",
            "recommendations",
            "risks",
            "nextSteps",
        ],
    }

    # ---- Call Gemini with retry-on-validation ----
    BANNED_WORDS = [
        "baseline",
        "regressors",
        "confidence bound",
        "error rate",
        "variance",
        "seasonality",
        "interpolation",
        "additive",
        "multiplicative",
    ]
    GREETING_PREFIXES = ["hi ", "hey ", "hello ", "good news", "greetings"]

    def validate_explanation(parsed: dict) -> list[str]:
        """
        Check the parsed explanation for common quality issues.
        Returns a list of problems found (empty = passed).
        """
        issues = []

        # Check overview mentions the total volume number
        overview = parsed.get("overview", "")
        volume_str = f"{total_forecast_volume:.0f}"
        if volume_str not in overview:
            issues.append(
                f"The 'overview' must include the exact total projected volume ({volume_str})."
            )

        # Check for greeting openers
        overview_lower = overview.lower().strip()
        for greeting in GREETING_PREFIXES:
            if overview_lower.startswith(greeting):
                issues.append(
                    f"Do NOT start the overview with a greeting like '{greeting.strip()}'. Jump straight into the insight."
                )
                break

        # Check for banned terms across all text fields
        all_text = overview + parsed.get("patterns", "") + parsed.get("reliability", "")
        all_text += " ".join(parsed.get("recommendations", []))
        all_text += " ".join(parsed.get("risks", []))
        all_text += " ".join(parsed.get("nextSteps", []))
        all_text_lower = all_text.lower()
        found_banned = [w for w in BANNED_WORDS if w in all_text_lower]
        if found_banned:
            issues.append(
                f"Avoid these technical terms: {found_banned}. Use simpler alternatives."
            )

        # Check that patterns mentions magnitudes for both peak and low month
        patterns = parsed.get("patterns", "").lower()
        if peak_month.lower() in patterns and low_month.lower() in patterns:
            # Both months mentioned — check if numbers are included
            import re

            numbers_in_patterns = re.findall(r"\d+", patterns)
            if len(numbers_in_patterns) < 2:
                issues.append(
                    "In 'patterns', include the specific magnitude (number of units) for BOTH the busiest and slowest month."
                )

        return issues

    print(f"  Calling {model_name}...")
    max_attempts = 2
    validation_issues: list[str] = []  # guard against unbound reference on retry
    for attempt in range(1, max_attempts + 1):
        try:
            from google.genai.types import GenerateContentConfig

            call_prompt = prompt
            if attempt > 1:
                # On retry, append the validation feedback as a hint
                hint = "\n".join([f"- {issue}" for issue in validation_issues])
                call_prompt = (
                    prompt
                    + f"\n\nYour previous response had these issues. Please fix them:\n{hint}\n"
                )
                print(
                    f"  ⚠ Retrying with validation feedback (attempt {attempt}/{max_attempts})..."
                )

            response = client.models.generate_content(
                model=model_name,
                contents=call_prompt,
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0.3,
                ),
            )
            explanation = response.text

            import json

            explanation_parsed = json.loads(explanation)

            # Validate the response
            validation_issues = validate_explanation(explanation_parsed)
            if validation_issues:
                print(f"  ⚠ Validation issues found: {validation_issues}")
                if attempt < max_attempts:
                    continue  # Retry with hints
                else:
                    print(
                        f"  ⚠ Returning response despite {len(validation_issues)} issue(s) after {max_attempts} attempts"
                    )

            print(f"  ✓ Received explanation (parsed successfully, attempt {attempt})")
            return explanation_parsed
        except json.JSONDecodeError:
            print(f"  ⚠ Gemini returned invalid JSON (attempt {attempt})")
            if attempt >= max_attempts:
                print(f"    Last response: {explanation[:200]}...")
                return None
        except Exception as e:
            print(f"  ✗ Gemini API error: {e}")
            return None

    return None


# ============================================================
# STEP 9: PRINT RESULTS
# ============================================================


def print_results(frontend_data: dict, explanation: str | None):
    """Print a formatted summary of all pipeline results."""
    print("\n" + "=" * 60)
    print("FORECAST RESULTS")
    print("=" * 60)
    m = frontend_data["metrics"]
    print(f"  Product:    {frontend_data['productName']}")
    print(f"  Historical: {len(frontend_data['historical'])} data points")
    print(f"  Forecast:   {len(frontend_data['forecast'])} data points")
    print(f"  Model:      {frontend_data.get('selectedModel', 'prophet')}")
    demand_profile = frontend_data.get("demandProfile", {})
    if demand_profile:
        print(f"  Demand:     {demand_profile.get('classification', 'unknown')}")
        if demand_profile.get("summary"):
            print(f"  Why:        {demand_profile['summary']}")
    model_selection = frontend_data.get("modelSelection", {})
    if model_selection.get("summary"):
        print(f"  Selection:  {model_selection['summary']}")
    print(f"  MAPE:       {m.get('mape', 'N/A')}% ({m.get('mape_rating', 'N/A')})")
    print(f"  WAPE:       {m.get('wape', 'N/A')}")
    print(f"  sMAPE:      {m.get('smape', 'N/A')}")
    print(f"  MASE:       {m.get('mase', 'N/A')}")
    print(f"  RMSE:       {m.get('rmse', 'N/A')}")
    print(f"  MAE:        {m.get('mae', 'N/A')}")

    if explanation:
        print("\n" + "-" * 60)
        print("AI EXPLANATION (Gemini)")
        print("-" * 60)
        print(explanation)

    # Save frontend-ready JSON
    output_path = Path(f"forecast_output_{frontend_data['productId']}.json")
    output = {**frontend_data, "explanation": explanation}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  ✓ Saved frontend-ready JSON: {output_path.resolve()}")


# ============================================================
# MAIN PIPELINE ORCHESTRATOR
# ============================================================


def load_tuned_params_cache(cache_path: str = "tuned_params_cache.json") -> dict:
    """Load cached tuned parameters from disk."""
    try:
        if Path(cache_path).exists():
            with open(cache_path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_tuned_params_cache(
    product_id: str,
    params: dict,
    cache_path: str = "tuned_params_cache.json",
):
    """Save tuned parameters for a product to the cache file."""
    cache = load_tuned_params_cache(cache_path)
    cache[product_id] = {
        **params,
        "cached_at": datetime.now().isoformat(),
    }
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2, default=str)


def run_pipeline(
    csv_path: str,
    product_id: str | None = None,
    horizon_days: int = 90,
    country: str | None = None,
    aggregation: str = "daily",
    custom_holidays: list[dict] | None = None,
    skip_gemini: bool = False,
    gemini_model: str = "gemini-3-flash-preview",
    use_weather: bool = False,
    latitude: float | None = None,
    longitude: float | None = None,
    enable_tuning: bool = False,
    tune_trials: int = 30,
    forecast_all: bool = False,
    no_cache: bool = False,
    column_map: dict | None = None,
    gap_fill_method: str = "interpolate",
    holidays_df: pd.DataFrame | None = None,
    external_regressors_df: pd.DataFrame | None = None,
    outlier_method: str = "cap",
    outlier_iqr_multiplier: float = 1.5,
    cv_initial_days: int | None = None,
    cv_horizon_days: int | None = None,
    cv_period_days: int | None = None,
    candidate_models: list[str] | None = None,
    auto_select_model: bool = False,
    selection_metric: str = "auto",
    auto_detect_models: bool = True,
):
    """
    Run the complete forecasting pipeline end-to-end.

    Supports single-product, multi-product (comma-separated), or
    all-products mode. Steps 1–4.5 run once, then steps 5–10
    loop per product.

    This function orchestrates all steps in order:
    1. Load CSV
    2. Validate structure
    3. Assess data quality + build health scorecard
    4. Select product(s)
    4.5. Fetch weather data (if enabled and location provided)
    --- per product ---
    5. Preprocess for Prophet (with configurable gap fill, outlier capping, regressors)
    5.5. Hyperparameter tuning with Optuna (if enabled)
    6. Train Prophet model (with monthly seasonality, user-supplied holidays, regressors)
    6.5. Detect trend changes
    7. Calculate accuracy metrics
    8. Format results for frontend
    9. Generate Gemini explanation
    10. Output results
    """
    print("\n" + "=" * 60)
    print("FORECASTING PIPELINE")
    print("=" * 60)
    print(f"  Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Step 1: Load CSV
    print(f"\n{'─' * 60}")
    print("STEP 1: Loading CSV")
    print(f"{'─' * 60}")
    df = load_csv(csv_path, column_map=column_map)

    # Step 2: Validate structure (also cleans edge cases)
    print(f"\n{'─' * 60}")
    print("STEP 2: Validating Structure")
    print(f"{'─' * 60}")
    df, validation_warnings = validate_structure(df)
    for w in validation_warnings:
        print(f"  ⚠ {w}")

    # Step 3: Data quality assessment + health scorecard
    print(f"\n{'─' * 60}")
    print("STEP 3: Data Quality Assessment")
    print(f"{'─' * 60}")
    quality_report = assess_data_quality(df, validation_warnings)
    data_health = build_data_health_scorecard(df, quality_report, validation_warnings)

    # Step 4: Select product(s)
    print(f"\n{'─' * 60}")
    print("STEP 4: Selecting Product(s)")
    print(f"{'─' * 60}")

    # Cast entirely to string to prevent numpy.int64 JSON fallback errors in dicts/json checks and allow for direct matching.
    df["product_id"] = df["product_id"].astype(str)
    available = sorted(df["product_id"].unique())

    if forecast_all:
        product_ids = available
        print(f"  Forecasting ALL products: {product_ids}")
    elif product_id and "," in product_id:
        # Comma-separated product list
        product_ids = [p.strip() for p in product_id.split(",")]
        invalid = [p for p in product_ids if p not in available]
        if invalid:
            print(f"  ✗ Products not found: {invalid}. Available: {available}")
            sys.exit(1)
        print(f"  Selected products: {product_ids}")
    elif product_id:
        if product_id not in available:
            print(f"  ✗ Product '{product_id}' not found. Available: {available}")
            sys.exit(1)
        product_ids = [product_id]
        print(f"  Selected: {product_id}")
    else:
        product_ids = [available[0]]
        print(f"  No product specified — defaulting to: {product_ids[0]}")

    # Step 4.5: Fetch weather data (if enabled) — runs ONCE for all products
    weather_data = None
    if use_weather:
        print(f"\n{'─' * 60}")
        print("STEP 4.5: Fetching Weather Data")
        print(f"{'─' * 60}")
        if latitude is None or longitude is None:
            print("  ✗ --weather requires both --latitude and --longitude")
            sys.exit(1)
        df["date"] = pd.to_datetime(df["date"])
        weather_start = df["date"].min().strftime("%Y-%m-%d")
        weather_end = df["date"].max().strftime("%Y-%m-%d")
        weather_data = fetch_weather_data(
            weather_start, weather_end, latitude, longitude
        )

    # Load cached tuned params (if available)
    params_cache = load_tuned_params_cache() if not no_cache else {}

    # ---- Run per product ----
    all_results = []
    summary_rows = []

    for idx, pid in enumerate(product_ids):
        if len(product_ids) > 1:
            print(f"\n{'=' * 60}")
            print(f"PRODUCT {idx + 1}/{len(product_ids)}: {pid}")
            print(f"{'=' * 60}")

        stats = quality_report["product_stats"].get(pid, {})
        pname = stats.get("name", "Unknown")
        if not stats.get("has_sufficient_data", True):
            print(
                f"  ⚠ WARNING: {pid} has only {stats.get('months_of_data', '?')} months of data"
            )

        # Step 5: Preprocess
        print(f"\n{'─' * 60}")
        print("STEP 5: Preprocessing")
        print(f"{'─' * 60}")
        product_holidays = select_product_holidays(holidays_df, pid)
        product_regressors = select_product_regressors(external_regressors_df, pid)
        processed = preprocess_for_prophet(
            df,
            pid,
            aggregation,
            weather_data=weather_data,
            external_regressors=product_regressors,
            gap_fill_method=gap_fill_method,
            outlier_method=outlier_method,
            outlier_iqr_multiplier=outlier_iqr_multiplier,
        )

        cv_config = determine_cv_config(
            processed,
            initial_days=cv_initial_days,
            horizon_days=cv_horizon_days,
            period_days=cv_period_days,
        )
        print(
            f"  ✓ Backtest config: initial={cv_config['initial_days']}d, "
            f"horizon={cv_config['horizon_days']}d, period={cv_config['period_days']}d"
        )

        demand_profile = detect_demand_profile(processed)
        demand_profile["summary"] = summarize_demand_profile(demand_profile)
        print(
            f"  ✓ Demand profile: {demand_profile['classification']} "
            f"(ADI={demand_profile['adi']}, CV²={demand_profile['cv2']}, zero_ratio={demand_profile['zeroRatio']})"
        )
        print(f"  ✓ Demand summary: {demand_profile['summary']}")

        requested_models = candidate_models or ["auto"]
        if auto_detect_models:
            requested_models = resolve_candidate_models(
                requested_models, demand_profile
            )
        effective_selection_metric = resolve_selection_metric(
            selection_metric, demand_profile
        )
        if auto_select_model:
            print(f"  ✓ Model candidates: {', '.join(requested_models)}")
            if effective_selection_metric != selection_metric:
                print(
                    f"  ✓ Selection metric auto-switched to: {effective_selection_metric} "
                    f"for {demand_profile['classification']} demand"
                )
        selected_model = requested_models[0]
        comparison_rows = []
        pre_tune_rows = []
        selection_details = {}

        # Step 5.5: Model backtesting / selection
        print(f"\n{'─' * 60}")
        print("STEP 5.5: Model Backtesting")
        print(f"{'─' * 60}")
        (
            best_model_metrics,
            comparison_rows,
            selection_details,
        ) = backtest_candidate_models(
            processed,
            aggregation,
            requested_models,
            effective_selection_metric,
            cv_config,
            country=country,
            custom_holidays=product_holidays,
        )
        pre_tune_rows = [dict(row) for row in comparison_rows]
        if auto_select_model:
            selected_model = best_model_metrics["model"]
            print(
                f"  ✓ Selected best model: {selected_model} "
                f"({best_model_metrics.get('selection_metric_used', effective_selection_metric)}="
                f"{best_model_metrics.get(best_model_metrics.get('selection_metric_used', effective_selection_metric))})"
            )
        else:
            print(f"  ✓ Using requested model: {selected_model}")

        # Step 5.6: Hyperparameter tuning
        tuned_params = None
        if enable_tuning and selected_model == "prophet":
            # Check cache first
            if pid in params_cache and not no_cache:
                tuned_params = params_cache[pid]
                print(f"\n  ✓ Loaded cached tuned params for {pid}")
                print(f"    (cached at: {tuned_params.get('cached_at', 'unknown')})")
            else:
                print(f"\n{'─' * 60}")
                print("STEP 5.6: Hyperparameter Tuning (Optuna)")
                print(f"{'─' * 60}")
                tuned_params = tune_hyperparameters(
                    processed,
                    n_trials=tune_trials,
                    use_weather=use_weather,
                    country=country,
                    custom_holidays=product_holidays,
                    cv_initial_days=cv_config["initial_days"],
                    cv_horizon_days=cv_config["horizon_days"],
                    cv_period_days=cv_config["period_days"],
                )
                # Cache the results
                save_tuned_params_cache(pid, tuned_params)
                print(f"  ✓ Cached tuned params for {pid}")

            (
                best_model_metrics,
                comparison_rows,
                selection_details,
            ) = backtest_candidate_models(
                processed,
                aggregation,
                requested_models,
                effective_selection_metric,
                cv_config,
                country=country,
                custom_holidays=product_holidays,
                tuned_params=tuned_params,
            )
            if auto_select_model:
                selected_model = best_model_metrics["model"]
                print(
                    f"  ✓ Final model after tuning-aware re-comparison: {selected_model} "
                    f"({best_model_metrics.get('selection_metric_used', effective_selection_metric)}="
                    f"{best_model_metrics.get(best_model_metrics.get('selection_metric_used', effective_selection_metric))})"
                )
        elif enable_tuning and selected_model != "prophet":
            print(
                f"\n  ℹ Tuning skipped because selected model is {selected_model}, not prophet"
            )
        else:
            print(f"\n  ℹ Hyperparameter tuning disabled (use --tune to enable)")

        # Step 6: Train Prophet
        print(f"\n{'─' * 60}")
        print("STEP 6: Training Selected Model")
        print(f"{'─' * 60}")
        if selected_model == "prophet":
            model, forecast = train_prophet(
                processed,
                horizon_days,
                country,
                product_holidays,
                use_weather=use_weather,
                weather_data=weather_data,
                latitude=latitude,
                longitude=longitude,
                tuned_params=tuned_params,
                external_regressors=product_regressors,
            )
        else:
            model, forecast = build_baseline_forecast_frame(
                processed, selected_model, horizon_days, aggregation
            )
            print(f"  ✓ Trained baseline model: {selected_model}")
            print(f"  ✓ Generated {horizon_days}-day forecast")

        # Step 6.5: Trend change detection
        print(f"\n{'─' * 60}")
        print("STEP 6.5: Trend Change Detection")
        print(f"{'─' * 60}")
        trend_changes = (
            detect_trend_changes(model, forecast) if selected_model == "prophet" else []
        )
        if trend_changes:
            print(f"  ✓ Detected {len(trend_changes)} significant trend change(s):")
            for tc in trend_changes:
                arrow = "↑" if tc["direction"] == "up" else "↓"
                print(f"    {arrow} {tc['date']}: {tc['description']}")
        else:
            print(f"  ✓ No significant trend changes detected")

        # Step 7: Cross-validation metrics
        print(f"\n{'─' * 60}")
        print("STEP 7: Cross-Validation & Metrics")
        print(f"{'─' * 60}")
        metrics = {k: v for k, v in best_model_metrics.items() if k != "model"}
        print(f"  ✓ Model: {selected_model}")
        print(f"  ✓ MAPE: {metrics.get('mape')}% ({metrics.get('mape_rating')})")
        print(f"  ✓ WAPE: {metrics.get('wape')}")
        print(f"  ✓ sMAPE:{metrics.get('smape')}")
        print(f"  ✓ MASE: {metrics.get('mase')}")
        print(f"  ✓ RMSE: {metrics.get('rmse')}")
        print(f"  ✓ MAE:  {metrics.get('mae')}")

        # Step 8: Format for frontend
        print(f"\n{'─' * 60}")
        print("STEP 8: Formatting for Frontend")
        print(f"{'─' * 60}")
        frontend_data = format_frontend_data(
            processed, forecast, model, metrics, pid, pname
        )

        # Add new data to the frontend output
        frontend_data["trendChanges"] = trend_changes
        frontend_data["selectedModel"] = selected_model
        frontend_data["demandProfile"] = demand_profile
        frontend_data["modelSelection"] = {
            "enabled": auto_select_model,
            "selectionMetric": selection_metric,
            "effectiveSelectionMetric": best_model_metrics.get(
                "selection_metric_used", effective_selection_metric
            ),
            "autoDetectedCandidates": auto_detect_models,
            "candidates": comparison_rows,
            "preTuneCandidates": pre_tune_rows,
            "postTuneCandidates": comparison_rows if tuned_params else None,
            "selectionDetails": {
                **selection_details,
                "phase": "post_tune" if tuned_params else "pre_tune",
            },
            "summary": summarize_model_selection(
                selected_model,
                best_model_metrics.get(
                    "selection_metric_used", effective_selection_metric
                ),
                comparison_rows,
                demand_profile,
                selection_details,
            ),
        }

        # Filter dataHealth warnings to only include this product's issues
        # (global warnings without a SKU- prefix are kept for all products)
        filtered_data_health = {**data_health}
        filtered_data_health["warnings"] = [
            w
            for w in data_health.get("warnings", [])
            if not w.startswith("SKU-") or w.startswith(pid)
        ]
        frontend_data["dataHealth"] = filtered_data_health
        if tuned_params:
            frontend_data["tuning"] = {
                "enabled": True,
                "trials": tune_trials,
                **{k: v for k, v in tuned_params.items() if k != "cached_at"},
            }
        else:
            frontend_data["tuning"] = {"enabled": False}

        print(f"  ✓ Historical data points: {len(frontend_data['historical'])}")
        print(f"  ✓ Forecast data points:   {len(frontend_data['forecast'])}")
        print(f"  ✓ Components: trend, weekly, yearly")
        print(f"  ✓ Trend changes: {len(trend_changes)}")
        print(
            f"  ✓ Data health: {data_health['overallScore']}/100 ({data_health['rating']})"
        )

        # Step 9: Gemini explanation
        explanation = None
        if not skip_gemini:
            print(f"\n{'─' * 60}")
            print("STEP 9: AI Explanation (Gemini)")
            print(f"{'─' * 60}")
            explanation = generate_gemini_explanation(frontend_data, gemini_model)
        else:
            print(f"\n{'─' * 60}")
            print("STEP 9: AI Explanation — SKIPPED (--skip-gemini)")
            print(f"{'─' * 60}")

        # Step 10: Output results
        print(f"\n{'─' * 60}")
        print("STEP 10: Results")
        print(f"{'─' * 60}")
        print_results(frontend_data, explanation)

        all_results.append((frontend_data, explanation))
        summary_rows.append(
            {
                "product": pid,
                "name": pname,
                "model": selected_model,
                "mape": metrics.get("mape"),
                "mape_rating": metrics.get("mape_rating", "N/A"),
                "rmse": metrics.get("rmse"),
                "mae": metrics.get("mae"),
                "trend_changes": len(trend_changes),
            }
        )

    # ---- Print summary table (for multi-product runs) ----
    if len(product_ids) > 1:
        print(f"\n{'=' * 60}")
        print("BATCH SUMMARY")
        print(f"{'=' * 60}")
        print(
            f"  {'Product':<12} {'Name':<18} {'Model':<16} {'MAPE':>8} {'Rating':>10}"
        )
        print(f"  {'-' * 58}")
        for row in summary_rows:
            mape_str = f"{row['mape']}%" if row["mape"] is not None else "N/A"
            print(
                f"  {row['product']:<12} {row['name']:<18} {row['model']:<16} {mape_str:>8} {row['mape_rating']:>10}"
            )

    print(f"\n  Pipeline completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if len(all_results) == 1:
        return all_results[0]
    return all_results


# ============================================================
# COMMAND LINE INTERFACE
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the forecasting pipeline end-to-end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python pipeline_test.py --csv sample_sales_data.csv
    python pipeline_test.py --csv sample_sales_data.csv --product SKU-001
    python pipeline_test.py --csv sample_sales_data.csv --product SKU-001,SKU-003
    python pipeline_test.py --csv sample_sales_data.csv --all --skip-gemini
    python pipeline_test.py --csv sample_sales_data.csv --tune --tune-trials 15
    python pipeline_test.py --csv sample_sales_data.csv --country PH --holidays-csv holidays.csv
    python pipeline_test.py --csv sample_sales_data.csv --regressors-csv regressors.csv --regressor-cols promo,payday
    python pipeline_test.py --csv sample_sales_data.csv --weather --latitude 14.5995 --longitude 120.9842 --horizon 180
        """,
    )
    parser.add_argument("--csv", required=True, help="Path to the sales CSV file")
    parser.add_argument(
        "--product",
        default=None,
        help="Product ID(s) to forecast. Comma-separated for multiple (e.g., SKU-001,SKU-003)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="forecast_all",
        help="Forecast all products in the dataset",
    )
    parser.add_argument(
        "--horizon", type=int, default=90, help="Forecast horizon in days (default: 90)"
    )
    parser.add_argument(
        "--country",
        default=None,
        help="Optional country code for built-in holidays (e.g., PH, US)",
    )
    parser.add_argument(
        "--aggregation", choices=["daily", "weekly", "monthly"], default="daily"
    )
    parser.add_argument(
        "--gap-fill",
        choices=["interpolate", "zero", "ffill"],
        default="interpolate",
        help="How to fill missing dates before training (default: interpolate)",
    )
    parser.add_argument(
        "--outlier-method",
        choices=["cap", "remove", "none"],
        default="cap",
        help="How to handle detected outliers before training (default: cap)",
    )
    parser.add_argument(
        "--outlier-iqr-multiplier",
        type=float,
        default=1.5,
        help="IQR multiplier for outlier detection (default: 1.5)",
    )
    parser.add_argument(
        "--skip-gemini", action="store_true", help="Skip the Gemini AI explanation step"
    )
    parser.add_argument(
        "--gemini-model",
        default="gemini-3.1-flash-lite-preview",
        help="Gemini model to use (default: gemini-3.1-flash-lite-preview)",
    )
    parser.add_argument(
        "--weather",
        action="store_true",
        help="Enable weather regressors via Open-Meteo API (requires internet)",
    )
    parser.add_argument(
        "--latitude",
        type=float,
        default=None,
        help="Location latitude for weather data (required with --weather)",
    )
    parser.add_argument(
        "--longitude",
        type=float,
        default=None,
        help="Location longitude for weather data (required with --weather)",
    )
    parser.add_argument(
        "--tune",
        action="store_true",
        help="Enable Optuna hyperparameter tuning (slower but more accurate)",
    )
    parser.add_argument(
        "--tune-trials",
        type=int,
        default=30,
        help="Number of Optuna tuning trials (default: 30, more = slower)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached tuned parameters and re-tune from scratch",
    )

    parser.add_argument(
        "--holidays-csv",
        default=None,
        help="Optional CSV of custom holidays/events to add to the model",
    )
    parser.add_argument(
        "--holiday-date-col",
        default="ds",
        help="Date column in the holidays CSV (default: ds)",
    )
    parser.add_argument(
        "--holiday-name-col",
        default="holiday",
        help="Holiday/event name column in the holidays CSV (default: holiday)",
    )
    parser.add_argument(
        "--holiday-product-col",
        default=None,
        help="Optional product column in the holidays CSV for product-specific events",
    )
    parser.add_argument(
        "--holiday-lower-window-col",
        default=None,
        help="Optional lower_window column in the holidays CSV",
    )
    parser.add_argument(
        "--holiday-upper-window-col",
        default=None,
        help="Optional upper_window column in the holidays CSV",
    )

    parser.add_argument(
        "--regressors-csv",
        default=None,
        help="Optional CSV of external regressors (promo flags, payday flags, stockout flags, etc.)",
    )
    parser.add_argument(
        "--regressor-date-col",
        default="date",
        help="Date column in the regressors CSV (default: date)",
    )
    parser.add_argument(
        "--regressor-product-col",
        default=None,
        help="Optional product column in the regressors CSV for product-specific rows",
    )
    parser.add_argument(
        "--regressor-cols",
        default=None,
        help="Comma-separated regressor columns to use. Default: all non-date/non-product columns",
    )

    parser.add_argument(
        "--cv-initial-days",
        type=int,
        default=None,
        help="Initial training window for backtesting, in days",
    )
    parser.add_argument(
        "--cv-horizon-days",
        type=int,
        default=None,
        help="Forecast horizon for backtesting, in days",
    )
    parser.add_argument(
        "--cv-period-days",
        type=int,
        default=None,
        help="Step size between backtest folds, in days",
    )
    parser.add_argument(
        "--model-candidates",
        default="auto",
        help="Comma-separated candidate models for backtesting, or 'auto'. Supported: prophet,naive,seasonal_naive,croston_sba",
    )
    parser.add_argument(
        "--auto-select-model",
        action="store_true",
        help="Backtest candidate models and automatically choose the best one",
    )
    parser.add_argument(
        "--selection-metric",
        choices=["auto", "mape", "wape", "smape", "mase", "rmse", "mae"],
        default="auto",
        help="Metric used to choose the winning model when auto-selection is enabled. 'auto' uses MASE for intermittent/lumpy demand and WAPE otherwise",
    )
    parser.add_argument(
        "--no-auto-detect-models",
        action="store_true",
        help="Disable dataset-driven candidate model detection and use --model-candidates exactly as provided",
    )

    parser.add_argument(
        "--col-date", default="date", help="CSV column name for date (default: date)"
    )
    parser.add_argument(
        "--col-id",
        default="product_id",
        help="CSV column name for product ID (default: product_id)",
    )
    parser.add_argument(
        "--col-name",
        default="product_name",
        help="CSV column name for product name (default: product_name)",
    )
    parser.add_argument(
        "--col-qty",
        default="quantity_sold",
        help="CSV column name for quantity sold (default: quantity_sold)",
    )

    args = parser.parse_args()

    # Create mapping dict
    column_map = {
        "date": args.col_date,
        "product_id": args.col_id,
        "product_name": args.col_name,
        "quantity_sold": args.col_qty,
    }

    holiday_rows = load_custom_holidays(
        args.holidays_csv,
        date_col=args.holiday_date_col,
        name_col=args.holiday_name_col,
        product_col=args.holiday_product_col,
        lower_window_col=args.holiday_lower_window_col,
        upper_window_col=args.holiday_upper_window_col,
    )
    regressor_columns = (
        [c.strip() for c in args.regressor_cols.split(",")]
        if args.regressor_cols
        else None
    )
    external_regressors = load_external_regressors(
        args.regressors_csv,
        date_col=args.regressor_date_col,
        product_col=args.regressor_product_col,
        regressor_columns=regressor_columns,
    )
    candidate_models = [
        m.strip() for m in args.model_candidates.split(",") if m.strip()
    ]

    run_pipeline(
        csv_path=args.csv,
        product_id=args.product,
        horizon_days=args.horizon,
        country=args.country,
        aggregation=args.aggregation,
        custom_holidays=None,
        skip_gemini=args.skip_gemini,
        gemini_model=args.gemini_model,
        use_weather=args.weather,
        latitude=args.latitude,
        longitude=args.longitude,
        enable_tuning=args.tune,
        tune_trials=args.tune_trials,
        forecast_all=args.forecast_all,
        no_cache=args.no_cache,
        column_map=column_map,
        gap_fill_method=args.gap_fill,
        holidays_df=holiday_rows,
        external_regressors_df=external_regressors,
        outlier_method=args.outlier_method,
        outlier_iqr_multiplier=args.outlier_iqr_multiplier,
        cv_initial_days=args.cv_initial_days,
        cv_horizon_days=args.cv_horizon_days,
        cv_period_days=args.cv_period_days,
        candidate_models=candidate_models,
        auto_select_model=args.auto_select_model,
        selection_metric=args.selection_metric,
        auto_detect_models=not args.no_auto_detect_models,
    )
