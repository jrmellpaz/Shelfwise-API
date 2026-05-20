"""
Forecast Service — the core forecasting pipeline.

Migrated from pipeline_test.py Steps 4–8, adapted for FastAPI:
- Loads data from DB (SalesData model) instead of CSV
- Writes results to Forecast + ForecastResult ORM models
- All print() → logging
- All sys.exit() → raise exceptions
"""

import calendar
import logging
import math
import warnings
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests as http_requests
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import (
    ForecastFailedException,
    InsufficientDataException,
    NotFoundException,
)
from app.models.custom_holiday import CustomHoliday
from app.services.gemini_service import generate_gemini_explanation
from app.models.forecast import Forecast
from app.models.forecast_result import ForecastResult
from app.models.product import Product
from app.models.sales_data import SalesData

# Suppress Prophet's verbose Stan logging
warnings.filterwarnings("ignore", category=FutureWarning)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

FORECAST_PROGRESS_TOTAL = 5


def _get_freq_str(aggregation: str) -> str:
    if aggregation == "weekly":
        return "W"
    if aggregation == "monthly":
        return "MS"
    return "D"


def _scale_horizon_to_periods(horizon_days: int, aggregation: str) -> int:
    if aggregation == "weekly":
        return int(math.ceil(horizon_days / 7.0))
    if aggregation == "monthly":
        return int(math.ceil(horizon_days / 30.44))
    return horizon_days


def build_custom_holidays_df(db: Session, user_id) -> pd.DataFrame | None:
    """Query user's custom holidays and return a Prophet-compatible DataFrame.

    Prophet expects a DataFrame with columns: holiday, ds, lower_window, upper_window.
    Returns None if the user has no custom holidays.
    """
    rows = db.query(CustomHoliday).filter(CustomHoliday.user_id == user_id).all()
    if not rows:
        return None
    return pd.DataFrame(
        [
            {
                "holiday": r.name,
                "ds": pd.Timestamp(r.date),
                "lower_window": 0,
                "upper_window": 0,
            }
            for r in rows
        ]
    )


def _persist_forecast_progress(
    db: Session,
    forecast_record: Forecast,
    step: int,
    label: str,
) -> None:
    """Publish step N of FORECAST_PROGRESS_TOTAL for GET /forecasts poll clients."""
    forecast_record.progress_step = step
    forecast_record.progress_total = FORECAST_PROGRESS_TOTAL
    forecast_record.progress_label = label
    db.commit()


def _clear_forecast_progress(db: Session, forecast_record: Forecast) -> None:
    forecast_record.progress_step = None
    forecast_record.progress_total = None
    forecast_record.progress_label = None


class ForecastCancelledException(Exception):
    """Raised when a forecast is cancelled mid-pipeline."""
    pass


def _check_cancelled(db: Session, forecast_record: Forecast) -> None:
    """Re-read the forecast status from DB and abort if cancelled.

    Called between major pipeline steps so the background task can
    exit early when the user cancels via POST /forecasts/{id}/cancel.
    """
    db.refresh(forecast_record)
    if forecast_record.status == "cancelled":
        logger.info("Forecast %s was cancelled — aborting pipeline", forecast_record.id)
        raise ForecastCancelledException()


# ── Preprocessing ─────────────────────────────────────────────


def preprocess_for_prophet(
    df: pd.DataFrame,
    aggregation: str = "daily",
    weather_data: pd.DataFrame | None = None,
    gap_fill_method: str = "interpolate",
    outlier_method: str = "cap",
    outlier_iqr_multiplier: float = 1.5,
) -> pd.DataFrame:
    """Prepare data for Prophet: rename cols, fill gaps, handle outliers."""
    pdf = df.copy()
    pdf["date"] = pd.to_datetime(pdf["date"])

    # Remove duplicates
    before_dedup = len(pdf)
    pdf = pdf.drop_duplicates(subset=["date"], keep="first")
    dupes_removed = before_dedup - len(pdf)
    if dupes_removed > 0:
        logger.info("Removed %d duplicate dates", dupes_removed)

    # Rename to Prophet format
    pdf = pdf.rename(columns={"date": "ds", "quantity_sold": "y"})
    pdf = pdf[["ds", "y"]].sort_values("ds").reset_index(drop=True)

    # Ensure numeric, clamp negatives
    pdf["y"] = pd.to_numeric(pdf["y"], errors="coerce").fillna(0)
    n_neg = (pdf["y"] < 0).sum()
    if n_neg > 0:
        pdf["y"] = pdf["y"].clip(lower=0)

    # Fill missing dates
    full_range = pd.date_range(start=pdf["ds"].min(), end=pdf["ds"].max(), freq="D")
    pdf = pdf.set_index("ds").reindex(full_range).reset_index()
    pdf.columns = ["ds", "y"]
    n_missing = int(pdf["y"].isna().sum())

    if gap_fill_method == "interpolate":
        pdf["y"] = pdf["y"].interpolate(method="linear").fillna(0)
    elif gap_fill_method == "zero":
        pdf["y"] = pdf["y"].fillna(0)
    elif gap_fill_method == "ffill":
        pdf["y"] = pdf["y"].ffill().fillna(0)

    if n_missing > 0:
        logger.info("Filled %d missing dates using %s", n_missing, gap_fill_method)

    # Outlier handling (IQR on positive values)
    positive_values = pdf.loc[pdf["y"] > 0, "y"]
    if len(positive_values) >= 8 and outlier_method != "none":
        q1 = positive_values.quantile(0.25)
        q3 = positive_values.quantile(0.75)
        iqr = q3 - q1

        if iqr > 0:
            lower_bound = max(0, q1 - outlier_iqr_multiplier * iqr)
            upper_bound = q3 + outlier_iqr_multiplier * iqr
            positive_mask = pdf["y"] > 0
            total_outliers = int(
                ((pdf["y"] < lower_bound) & positive_mask).sum()
                + ((pdf["y"] > upper_bound) & positive_mask).sum()
            )

            if total_outliers > 0 and outlier_method == "cap":
                pdf.loc[positive_mask, "y"] = pdf.loc[positive_mask, "y"].clip(
                    lower=lower_bound, upper=upper_bound
                )
                logger.info(
                    "Capped %d outliers (IQR: %.0f–%.0f)",
                    total_outliers,
                    lower_bound,
                    upper_bound,
                )
            elif total_outliers > 0 and outlier_method == "remove":
                pdf = pdf[
                    (~positive_mask)
                    | ((pdf["y"] >= lower_bound) & (pdf["y"] <= upper_bound))
                ].reset_index(drop=True)

    # Merge weather if available
    if weather_data is not None:
        pdf = pdf.merge(
            weather_data[["ds", "temperature", "precipitation"]], on="ds", how="left"
        )
        pdf["temperature"] = pdf["temperature"].ffill().bfill()
        pdf["precipitation"] = pdf["precipitation"].ffill().bfill()

    # Time aggregation
    if aggregation == "weekly":
        agg_dict: dict[str, str] = {"y": "sum"}
        if "temperature" in pdf.columns:
            agg_dict["temperature"] = "mean"
            agg_dict["precipitation"] = "sum"
        pdf = pdf.set_index("ds").resample("W").agg(agg_dict).reset_index()
    elif aggregation == "monthly":
        agg_dict = {"y": "sum"}
        if "temperature" in pdf.columns:
            agg_dict["temperature"] = "mean"
            agg_dict["precipitation"] = "sum"
        pdf = pdf.set_index("ds").resample("MS").agg(agg_dict).reset_index()

    pdf["y"] = pdf["y"].astype(float)
    return pdf


# ── Demand Profiling ──────────────────────────────────────────


def detect_demand_profile(df: pd.DataFrame) -> dict:
    """Classify demand using ADI/CV² framework."""
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

    # Auto-include XGBoost when seasonality is weak
    from app.services.xgboost_model import (
        detect_seasonality_strength,
        MIN_ROWS_XGBOOST,
    )

    if total_periods >= MIN_ROWS_XGBOOST:
        autocorr_7 = detect_seasonality_strength(values, lag=7)
        if autocorr_7 is not None and abs(autocorr_7) < 0.3:
            # Weak weekly seasonality — XGBoost may outperform Prophet
            if "xgboost" not in recommended:
                recommended.insert(0, "xgboost")
            logger.info(
                "Weak seasonality detected (autocorr@7=%.3f) — "
                "adding XGBoost to candidates",
                autocorr_7,
            )

    profile = {
        "classification": classification,
        "adi": round(float(adi), 3),
        "cv2": round(float(cv2), 3),
        "zeroRatio": round(zero_ratio, 3),
        "nonZeroPeriods": non_zero_periods,
        "totalPeriods": total_periods,
        "recommendedModels": recommended,
    }
    profile["summary"] = _summarize_demand_profile(profile)
    return profile


def _summarize_demand_profile(dp: dict) -> str:
    c = dp["classification"]
    if c == "all_zero":
        return "No non-zero sales found — treated as an all-zero series."
    if c == "smooth":
        return (
            f"Regular sales with stable order sizes (ADI={dp['adi']}, CV²={dp['cv2']})."
        )
    if c == "erratic":
        return f"Frequent sales but volatile order sizes (ADI={dp['adi']}, CV²={dp['cv2']})."
    if c == "intermittent":
        return f"Many zero-sale periods with consistent order sizes (ADI={dp['adi']}, CV²={dp['cv2']})."
    if c == "lumpy":
        return f"Many zero-sale periods and volatile order sizes (ADI={dp['adi']}, CV²={dp['cv2']})."
    return "Could not classify demand pattern."


# ── Model Selection ───────────────────────────────────────────


def resolve_candidate_models(
    requested: list[str] | None,
    demand_profile: dict,
) -> list[str]:
    if not requested or requested == ["auto"]:
        return demand_profile["recommendedModels"]
    normalized = [m.strip() for m in requested if m.strip()]
    return normalized if normalized else demand_profile["recommendedModels"]


def resolve_selection_metric(
    requested: str | None,
    demand_profile: dict,
) -> str:
    if requested and requested != "auto":
        return requested
    c = demand_profile.get("classification")
    return "mase" if c in {"intermittent", "lumpy", "all_zero"} else "wape"


# ── Cross-Validation & Backtesting ────────────────────────────


def determine_cv_config(
    df: pd.DataFrame,
    initial_days: int | None = None,
    horizon_days: int | None = None,
    period_days: int | None = None,
    aggregation: str = "daily",
) -> dict:
    n_rows = len(df)

    if aggregation == "daily":
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

    default_initial_rows = max(6, int(n_rows * 0.6))
    default_horizon_rows = max(2, min(6, int(n_rows * 0.2)))
    default_period_rows = default_horizon_rows

    config = {
        "initial_rows": initial_days or default_initial_rows,
        "horizon_rows": horizon_days or default_horizon_rows,
        "period_rows": period_days or default_period_rows,
        "_row_based": True,
    }
    if config["initial_rows"] + config["horizon_rows"] >= n_rows:
        config["initial_rows"] = max(3, n_rows - config["horizon_rows"] - 1)
    return config


def _generate_backtest_folds(df, cv_config):
    if cv_config.get("_row_based"):
        return _generate_backtest_folds_row_based(df, cv_config)

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


def _generate_backtest_folds_row_based(df, cv_config):
    sorted_dates = df["ds"].sort_values().reset_index(drop=True)
    n = len(sorted_dates)
    initial = cv_config["initial_rows"]
    horizon = cv_config["horizon_rows"]
    period = cv_config["period_rows"]
    folds = []
    idx = initial
    while idx + horizon <= n:
        cutoff = sorted_dates.iloc[idx - 1]
        horizon_end = sorted_dates.iloc[min(idx + horizon - 1, n - 1)]
        folds.append((cutoff, horizon_end))
        idx += period
    if not folds and n > 2:
        cutoff = sorted_dates.iloc[max(0, n - horizon - 1)]
        folds.append((cutoff, sorted_dates.iloc[-1]))
    return folds


def compute_error_metrics(y_true, y_pred, insample_values) -> dict:
    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)
    insample_values = np.array(insample_values, dtype=float)

    abs_error = np.abs(y_true - y_pred)
    squared_error = (y_true - y_pred) ** 2
    non_zero_mask = y_true != 0
    wape_denom = np.abs(y_true).sum()
    smape_denom = np.abs(y_true) + np.abs(y_pred)
    naive_diffs = np.abs(np.diff(insample_values))
    mase_denom = naive_diffs.mean() if len(naive_diffs) > 0 else 0

    mape = (
        float(np.mean(abs_error[non_zero_mask] / np.abs(y_true[non_zero_mask]))) * 100
        if non_zero_mask.any()
        else None
    )

    smape_terms = np.zeros_like(abs_error, dtype=float)
    np.divide(2 * abs_error, smape_denom, out=smape_terms, where=smape_denom != 0)

    mean_abs_error = float(np.mean(abs_error)) if len(abs_error) > 0 else 0.0

    result = {
        "mape": round(mape, 2) if mape is not None else None,
        "wape": round(float(abs_error.sum() / wape_denom) * 100, 2)
        if wape_denom > 0
        else None,
        "smape": round(float(np.mean(smape_terms)) * 100, 2),
        "mase": round(float(mean_abs_error / mase_denom), 3)
        if mase_denom > 0
        else (0.0 if mean_abs_error == 0 else None),
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


def _infer_season_length(aggregation: str) -> int:
    if aggregation == "weekly":
        return 4
    if aggregation == "monthly":
        return 12
    return 7


def _build_baseline_forecast(
    model_name: str, train_values: np.ndarray, horizon: int, season_length: int
) -> np.ndarray:
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
        demand_est = train_values[first_idx]
        interval_est = 1.0
        interval = 1.0
        for value in train_values[first_idx + 1 :]:
            if value > 0:
                demand_est += alpha * (value - demand_est)
                interval_est += alpha * (interval - interval_est)
                interval = 1.0
            else:
                interval += 1.0
        rate = (1 - alpha / 2) * demand_est / max(interval_est, 1e-9)
        return np.repeat(max(0.0, rate), horizon).astype(float)

    raise ValueError(f"Unsupported baseline model: {model_name}")


def _backtest_single_model(
    model_name: str,
    df: pd.DataFrame,
    aggregation: str,
    cv_config: dict,
    country: str | None = None,
    tuned_params: dict | None = None,
    custom_holidays_df: pd.DataFrame | None = None,
) -> dict:
    """Run rolling backtests for a single candidate model."""
    # XGBoost has its own backtest implementation
    if model_name == "xgboost":
        from app.services.xgboost_model import backtest_xgb_model

        return backtest_xgb_model(
            df,
            aggregation,
            cv_config,
            country=country,
            custom_holidays_df=custom_holidays_df,
            xgb_params=tuned_params,
        )

    from prophet import Prophet

    season_length = _infer_season_length(aggregation)
    regressor_columns = [c for c in df.columns if c not in {"ds", "y"}]
    y_true_all: list[float] = []
    y_pred_all: list[float] = []
    folds = _generate_backtest_folds(df, cv_config)

    if not folds:
        raise ForecastFailedException("Unable to generate backtest folds")

    freq_str = _get_freq_str(aggregation)

    for cutoff, horizon_end in folds:
        train_df = df[df["ds"] <= cutoff].copy()
        test_df = df[(df["ds"] > cutoff) & (df["ds"] <= horizon_end)].copy()
        if test_df.empty:
            continue

        if model_name == "prophet":
            avg_sales = train_df["y"].mean()
            std_sales = train_df["y"].std()
            cv_val = std_sales / avg_sales if avg_sales > 0 else 0
            s_mode = "multiplicative" if cv_val > 0.5 else "additive"
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
            mfo = tuned_params.get("monthly_fourier_order", 5) if tuned_params else 5
            s_mode = (
                tuned_params.get("seasonality_mode", s_mode) if tuned_params else s_mode
            )

            model = Prophet(
                changepoint_prior_scale=cps,
                seasonality_prior_scale=sps,
                seasonality_mode=s_mode,
                interval_width=0.80,
                daily_seasonality=False,
                weekly_seasonality=(aggregation == "daily"),
                yearly_seasonality=True,
                holidays=custom_holidays_df,
            )

            if aggregation == "daily":
                model.add_seasonality(name="monthly", period=30.5, fourier_order=mfo)
            elif aggregation == "weekly":
                model.add_seasonality(name="monthly", period=4.34, fourier_order=mfo)

            for col in regressor_columns:
                model.add_regressor(col)
            if country:
                model.add_country_holidays(country_name=country)

            model.fit(train_df)
            future = model.make_future_dataframe(periods=len(test_df), freq=freq_str)
            if regressor_columns:
                known = pd.concat(
                    [
                        train_df[["ds", *regressor_columns]],
                        test_df[["ds", *regressor_columns]],
                    ]
                ).drop_duplicates(subset=["ds"], keep="last")
                future = future.merge(known, on="ds", how="left")
                future[regressor_columns] = (
                    future[regressor_columns].ffill().bfill().fillna(0)
                )
            forecast = model.predict(future)
            preds = (
                forecast.tail(len(test_df))["yhat"].clip(lower=0).to_numpy(dtype=float)
            )
        else:
            preds = _build_baseline_forecast(
                model_name,
                train_df["y"].to_numpy(dtype=float),
                len(test_df),
                season_length,
            )

        y_true_all.extend(test_df["y"].to_numpy(dtype=float))
        y_pred_all.extend(preds)

    metrics = compute_error_metrics(
        y_true_all, y_pred_all, df["y"].to_numpy(dtype=float)
    )
    metrics["model"] = model_name
    metrics["folds"] = len(folds)
    return metrics


def backtest_and_select(
    df: pd.DataFrame,
    aggregation: str,
    candidate_models: list[str],
    selection_metric: str,
    cv_config: dict,
    country: str | None = None,
    tuned_params: dict | None = None,
    custom_holidays_df: pd.DataFrame | None = None,
    xgb_tuned_params: dict | None = None,
) -> tuple[dict, list[dict], dict]:
    """Backtest all candidates and return the best plus comparison rows."""
    fallback_order = [selection_metric, "mase", "mae", "rmse", "smape", "wape", "mape"]
    results = []
    for model_name in candidate_models:
        try:
            # Route the correct tuned params to each model
            if model_name == "prophet":
                model_params = tuned_params
            elif model_name == "xgboost":
                model_params = xgb_tuned_params
            else:
                model_params = None

            metrics = _backtest_single_model(
                model_name,
                df,
                aggregation,
                cv_config,
                country=country,
                tuned_params=model_params,
                custom_holidays_df=custom_holidays_df,
            )
            results.append(metrics)
        except Exception as e:
            logger.warning("Backtest failed for %s: %s", model_name, e)

    # Find best using fallback metric order
    chosen_metric = None
    valid_results: list[dict] = []
    for metric_name in fallback_order:
        valid_results = [r for r in results if r.get(metric_name) is not None]
        if valid_results:
            chosen_metric = metric_name
            break

    if not valid_results or chosen_metric is None:
        raise ForecastFailedException("No candidate produced a valid score")

    ordered = sorted(valid_results, key=lambda r: r[chosen_metric])
    best = ordered[0]

    # Runner-up
    runner_up = next((r for r in ordered if r["model"] != best["model"]), None)
    winner_score = best.get(chosen_metric)
    runner_score = runner_up.get(chosen_metric) if runner_up else None

    for row in results:
        row["selection_metric_used"] = chosen_metric

    selection_details = {
        "selectionMetricUsed": chosen_metric,
        "selectionMetricRequested": selection_metric,
        "winnerModel": best.get("model"),
        "winnerScore": winner_score,
        "runnerUpModel": runner_up.get("model") if runner_up else None,
        "runnerUpScore": runner_score,
    }

    return best, results, selection_details


# ── Optuna Hyperparameter Tuning ──────────────────────────────


def optuna_tune_prophet(
    df: pd.DataFrame,
    aggregation: str,
    cv_config: dict,
    country: str | None = None,
    n_trials: int = 30,
    custom_holidays_df: pd.DataFrame | None = None,
) -> dict | None:
    """Use Optuna Bayesian optimization to find optimal Prophet hyperparameters.

    Searches over:
    - changepoint_prior_scale: 0.001 – 0.5
    - seasonality_prior_scale: 0.01 – 10.0
    - seasonality_mode: additive / multiplicative
    - monthly_fourier_order: 0 – 5

    Each trial runs a Prophet cross-validation and evaluates MAPE.
    Returns the best parameter dict, or None if tuning fails entirely.
    """
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.warning("Optuna not installed — skipping hyperparameter tuning")
        return None

    logger.info("Starting Optuna tuning (%d trials)...", n_trials)

    def objective(trial: optuna.Trial) -> float:
        params = {
            "changepoint_prior_scale": trial.suggest_float(
                "changepoint_prior_scale", 0.001, 0.5, log=True
            ),
            "seasonality_prior_scale": trial.suggest_float(
                "seasonality_prior_scale", 0.01, 10.0, log=True
            ),
            "seasonality_mode": trial.suggest_categorical(
                "seasonality_mode", ["additive", "multiplicative"]
            ),
            "monthly_fourier_order": trial.suggest_int("monthly_fourier_order", 0, 5),
        }

        try:
            metrics = _backtest_single_model(
                "prophet",
                df,
                aggregation,
                cv_config,
                country=country,
                tuned_params=params,
                custom_holidays_df=custom_holidays_df,
            )
            mape = metrics.get("mape")
            if mape is None:
                return float("inf")
            return mape
        except Exception as e:
            logger.debug("Optuna trial failed: %s", e)
            return float("inf")

    try:
        study = optuna.create_study(direction="minimize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

        best_params = study.best_params
        best_value = study.best_value
        logger.info(
            "Optuna tuning complete — best MAPE: %.2f%%, params: %s",
            best_value,
            best_params,
        )
        return best_params

    except Exception as e:
        logger.warning("Optuna tuning failed: %s", e)
        return None


# ── Prophet Training ──────────────────────────────────────────


def train_prophet_model(
    df: pd.DataFrame,
    horizon_days: int = 90,
    country: str | None = None,
    tuned_params: dict | None = None,
    custom_holidays_df: pd.DataFrame | None = None,
    aggregation: str = "daily",
) -> tuple:
    """Configure, train Prophet, and generate forecast with correct temporal alignment."""
    from prophet import Prophet

    avg_sales = df["y"].mean()
    std_sales = df["y"].std()
    cv_val = std_sales / avg_sales if avg_sales > 0 else 0
    s_mode = "multiplicative" if cv_val > 0.5 else "additive"

    if tuned_params:
        cps = tuned_params.get("changepoint_prior_scale", 0.1)
        sps = tuned_params.get("seasonality_prior_scale", 10.0)
        s_mode = tuned_params.get("seasonality_mode", s_mode)
        mfo = tuned_params.get("monthly_fourier_order", 5)
    else:
        cps, sps, mfo = 0.1, 10.0, 5

    regressor_columns = [c for c in df.columns if c not in {"ds", "y"}]

    is_daily = aggregation == "daily"
    is_weekly = aggregation == "weekly"

    model = Prophet(
        changepoint_prior_scale=cps,
        seasonality_prior_scale=sps,
        seasonality_mode=s_mode,
        interval_width=0.80,
        daily_seasonality=False,
        weekly_seasonality=is_daily,
        yearly_seasonality=True,
        holidays=custom_holidays_df,
    )

    if is_daily:
        model.add_seasonality(name="monthly", period=30.5, fourier_order=mfo)
    elif is_weekly:
        model.add_seasonality(name="monthly", period=4.34, fourier_order=mfo)

    for col in regressor_columns:
        model.add_regressor(col)
    if country:
        model.add_country_holidays(country_name=country)

    logger.info("Training Prophet model on %s aggregation...", aggregation)
    model.fit(df)

    periods = _scale_horizon_to_periods(horizon_days, aggregation)
    freq_str = _get_freq_str(aggregation)

    future = model.make_future_dataframe(periods=periods, freq=freq_str)

    if regressor_columns:
        known = df[["ds", *regressor_columns]].drop_duplicates(
            subset=["ds"], keep="last"
        )
        future = future.merge(known, on="ds", how="left")
        future[regressor_columns] = (
            future[regressor_columns].ffill().bfill().fillna(0)
        )

    forecast = model.predict(future)

    forecast["yhat"] = forecast["yhat"].clip(lower=0)
    forecast["yhat_lower"] = forecast["yhat_lower"].clip(lower=0)
    forecast["yhat_upper"] = forecast["yhat_upper"].clip(lower=0)

    logger.info("Generated %d-period forecast using frequency %s", periods, freq_str)
    return model, forecast


def build_baseline_forecast_frame(
    df: pd.DataFrame, model_name: str, horizon_days: int, aggregation: str
) -> tuple[dict, pd.DataFrame]:
    """Train a baseline model and produce future rows matching target frequency."""
    freq_str = _get_freq_str(aggregation)
    periods = _scale_horizon_to_periods(horizon_days, aggregation)

    future_dates = pd.date_range(
        start=df["ds"].max(),
        periods=periods + 1,
        freq=freq_str,
    )[1:]

    season_length = _infer_season_length(aggregation)
    preds = _build_baseline_forecast(
        model_name, df["y"].to_numpy(dtype=float), periods, season_length
    )
    residual_scale = float(df["y"].std()) if len(df) > 1 else 0.0
    forecast = pd.DataFrame(
        {
            "ds": future_dates,
            "yhat": preds,
            "yhat_lower": np.maximum(0, preds - 1.28 * residual_scale),
            "yhat_upper": preds + 1.28 * residual_scale,
        }
    )
    return {"model_name": model_name}, forecast


# ── Trend Change Detection ────────────────────────────────────


def detect_trend_changes(model, forecast_df: pd.DataFrame) -> list[dict]:
    """Extract significant trend changepoints from Prophet model."""
    changes: list[dict] = []
    try:
        if not hasattr(model, "changepoints") or model.changepoints is None:
            return changes
        changepoint_dates = model.changepoints
        if len(changepoint_dates) == 0:
            return changes
        deltas = model.params["delta"].mean(axis=0)
        trend = forecast_df[["ds", "trend"]].copy()

        for cp_date, delta in zip(changepoint_dates, deltas):
            delta_val = float(delta)
            if abs(delta_val) < 0.5:
                continue
            direction = "up" if delta_val > 0 else "down"
            closest_idx = (trend["ds"] - cp_date).abs().idxmin()
            trend_at_point = float(trend.loc[closest_idx, "trend"])
            changes.append(
                {
                    "date": cp_date.strftime("%Y-%m-%d"),
                    "direction": direction,
                    "magnitude": round(abs(delta_val), 2),
                    "trendAtChange": round(trend_at_point, 1),
                    "description": f"Trend {'increased' if direction == 'up' else 'decreased'} by {abs(delta_val):.1f} units/day",
                }
            )
        changes.sort(key=lambda x: x["magnitude"], reverse=True)
    except Exception as e:
        logger.warning("Could not extract trend changes: %s", e)
    return changes


# ── Format for Frontend ───────────────────────────────────────


def format_frontend_data(
    df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    metrics: dict,
    product_id: str,
    product_name: str,
) -> dict:
    """Shape all results into the JSON structure the frontend needs."""
    last_historical_date = df["ds"].max()

    # Historical data — sales are always whole units
    historical = [
        {"date": row["ds"].strftime("%Y-%m-%d"), "actual": int(round(float(row["y"])))}
        for _, row in df.iterrows()
    ]

    # Forecast data — inventory quantities are discrete; round up
    # predicted/upper (never understock) and floor lower bound.
    future_rows = forecast_df[forecast_df["ds"] > last_historical_date]
    forecast_data = [
        {
            "date": row["ds"].strftime("%Y-%m-%d"),
            "predicted": max(0, math.ceil(float(row["yhat"]))),
            "lowerBound": max(0, math.floor(float(row.get("yhat_lower", 0)))),
            "upperBound": max(0, math.ceil(float(row.get("yhat_upper", row["yhat"])))),
        }
        for _, row in future_rows.iterrows()
    ]

    # Trend component
    trend_data = []
    if "trend" in forecast_df.columns:
        trend_data = [
            {
                "date": row["ds"].strftime("%Y-%m-%d"),
                "value": round(float(row["trend"]), 1),
            }
            for _, row in forecast_df.iterrows()
        ]

    # Weekly seasonality
    weekly_data: list[dict] = []
    if "weekly" in forecast_df.columns:
        fc = forecast_df.copy()
        fc["dow"] = fc["ds"].dt.day_name()
        weekly_avg = fc.groupby("dow")["weekly"].mean()
        for day in [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]:
            if day in weekly_avg.index:
                weekly_data.append(
                    {"dayOfWeek": day, "effect": round(float(weekly_avg[day]), 2)}
                )

    # Yearly seasonality
    yearly_data: list[dict] = []
    if "yearly" in forecast_df.columns:
        fc = forecast_df.copy()
        yearly_avg = fc.groupby(fc["ds"].dt.month)["yearly"].mean()
        for month_num, effect in yearly_avg.items():
            yearly_data.append(
                {
                    "month": calendar.month_name[month_num],
                    "effect": round(float(effect), 2),
                }
            )

    return {
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


# ── Weather Helpers ───────────────────────────────────────────


def fetch_weather_data(
    start_date: str,
    end_date: str,
    latitude: float | None = None,
    longitude: float | None = None,
) -> pd.DataFrame | None:
    """Fetch historical weather from Open-Meteo."""
    latitude = latitude if latitude is not None else settings.DEFAULT_LATITUDE
    longitude = longitude if longitude is not None else settings.DEFAULT_LONGITUDE
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
        response = http_requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        weather_df = pd.DataFrame(
            {
                "ds": pd.to_datetime(data["daily"]["time"]),
                "temperature": data["daily"]["temperature_2m_mean"],
                "precipitation": data["daily"]["precipitation_sum"],
            }
        )
        return weather_df.ffill().bfill()
    except Exception as e:
        logger.warning("Failed to fetch weather data: %s", e)
        return None


def fetch_weather_forecast(
    latitude: float,
    longitude: float,
    days: int = 16,
) -> pd.DataFrame | None:
    """Fetch near-future weather forecast from Open-Meteo Forecast API.

    Returns up to 16 days of forecast data (daily temperature + precipitation).
    Used to provide regressor values for the near-future portion of the
    forecast horizon, rather than relying solely on forward-fill.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ["temperature_2m_mean", "precipitation_sum"],
        "forecast_days": min(days, 16),
        "timezone": "auto",
    }
    try:
        response = http_requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        weather_df = pd.DataFrame(
            {
                "ds": pd.to_datetime(data["daily"]["time"]),
                "temperature": data["daily"]["temperature_2m_mean"],
                "precipitation": data["daily"]["precipitation_sum"],
            }
        )
        return weather_df.ffill().bfill()
    except Exception as e:
        logger.warning("Failed to fetch weather forecast: %s", e)
        return None


def _resolve_user_location(user) -> tuple[float, float]:
    """Return (latitude, longitude) for a user, falling back to country capital."""
    from app.api.v1.profile import COUNTRY_CAPITALS

    if user.location_latitude is not None and user.location_longitude is not None:
        return (user.location_latitude, user.location_longitude)
    country = user.holiday_calendar or "PH"
    capital = COUNTRY_CAPITALS.get(country, COUNTRY_CAPITALS["PH"])
    return (capital[1], capital[2])


# ── Master Orchestrator ───────────────────────────────────────


def run_forecast(
    forecast_id: str,
    db: Session,
) -> None:
    """Run the full forecasting pipeline for a given Forecast record.

    Called as a BackgroundTask. Loads sales data from DB, runs the
    full pipeline, writes results back to the DB.
    """
    try:
        forecast_record = db.query(Forecast).filter(Forecast.id == forecast_id).first()
        if not forecast_record:
            logger.error("Forecast record %s not found", forecast_id)
            return

        product = (
            db.query(Product).filter(Product.id == forecast_record.product_id).first()
        )
        if not product:
            _clear_forecast_progress(db, forecast_record)
            forecast_record.status = "failed"
            forecast_record.error_message = "Product not found"
            db.commit()
            return

        # Load sales data from DB
        sales_rows = (
            db.query(SalesData)
            .filter(SalesData.product_id == product.id)
            .order_by(SalesData.date)
            .all()
        )
        if not sales_rows:
            _clear_forecast_progress(db, forecast_record)
            forecast_record.status = "failed"
            forecast_record.error_message = "No sales data available"
            db.commit()
            return

        df = pd.DataFrame(
            [
                {"date": r.date, "quantity_sold": float(r.quantity_sold)}
                for r in sales_rows
            ]
        )

        # Check minimum data length
        df["date"] = pd.to_datetime(df["date"])
        date_range_months = (df["date"].max() - df["date"].min()).days / 30.44
        if date_range_months < 2:
            _clear_forecast_progress(db, forecast_record)
            forecast_record.status = "failed"
            forecast_record.error_message = "Insufficient historical data"
            db.commit()
            return

        horizon_days = forecast_record.forecast_horizon or 90
        aggregation = forecast_record.time_granularity or "daily"
        country = None

        # Get user's holiday calendar
        from app.models.user import User

        user = db.query(User).filter(User.id == forecast_record.user_id).first()
        if user and user.holiday_calendar:
            country = user.holiday_calendar

        # Load user's custom holidays for Prophet
        custom_holidays_df = build_custom_holidays_df(db, forecast_record.user_id)

        # Fetch weather data for the user's location (if enabled)
        weather_data = None
        weather_enabled = getattr(user, "weather_enabled", True) if user else False
        if user and weather_enabled:
            lat, lng = _resolve_user_location(user)
            start_str = df["date"].min().strftime("%Y-%m-%d")
            end_str = df["date"].max().strftime("%Y-%m-%d")
            logger.info(
                "Fetching weather data for (%.4f, %.4f) from %s to %s",
                lat, lng, start_str, end_str,
            )
            weather_data = fetch_weather_data(start_str, end_str, lat, lng)

            # Also fetch near-future weather forecast and append
            forecast_weather = fetch_weather_forecast(lat, lng, days=min(horizon_days, 16))
            if weather_data is not None and forecast_weather is not None:
                weather_data = pd.concat(
                    [weather_data, forecast_weather], ignore_index=True
                ).drop_duplicates(subset=["ds"], keep="last").sort_values("ds").reset_index(drop=True)
            elif forecast_weather is not None:
                weather_data = forecast_weather

            if weather_data is not None:
                logger.info("Weather data loaded: %d rows", len(weather_data))
            else:
                logger.warning("Weather data unavailable — proceeding without regressors")

        # Step 1: Preprocess
        _persist_forecast_progress(db, forecast_record, 1, "Preparing data")
        _check_cancelled(db, forecast_record)
        logger.info("Preprocessing data for forecast %s", forecast_id)
        processed = preprocess_for_prophet(df, aggregation=aggregation, weather_data=weather_data)

        # Step 2: Demand profiling
        _persist_forecast_progress(db, forecast_record, 2, "Selecting model")
        _check_cancelled(db, forecast_record)
        demand_profile = detect_demand_profile(processed)
        forecast_record.demand_profile = demand_profile["classification"]
        db.commit()

        # Step 2.5: Optuna hyperparameter tuning (if enabled)
        init_params = forecast_record.model_parameters or {}
        enable_tuning = init_params.get("enable_tuning", False)
        tune_trials = init_params.get("tune_trials", 30)
        tuned_params = None

        candidates = resolve_candidate_models(None, demand_profile)
        sel_metric = resolve_selection_metric(None, demand_profile)
        cv_config = determine_cv_config(processed, aggregation=aggregation)

        if enable_tuning and "prophet" in candidates:
            _check_cancelled(db, forecast_record)
            logger.info("Running Optuna tuning for forecast %s", forecast_id)
            tuned_params = optuna_tune_prophet(
                processed,
                aggregation,
                cv_config,
                country=country,
                n_trials=tune_trials,
                custom_holidays_df=custom_holidays_df,
            )
            if tuned_params:
                forecast_record.tuned_parameters = tuned_params

        # Optuna tuning for XGBoost (separate param set)
        xgb_tuned_params = None
        if enable_tuning and "xgboost" in candidates:
            _check_cancelled(db, forecast_record)
            from app.services.xgboost_model import optuna_tune_xgboost

            logger.info("Running Optuna XGBoost tuning for forecast %s", forecast_id)
            xgb_tuned_params = optuna_tune_xgboost(
                processed,
                aggregation,
                cv_config,
                country=country,
                custom_holidays_df=custom_holidays_df,
                n_trials=tune_trials,
            )
            if xgb_tuned_params:
                existing_tuned = forecast_record.tuned_parameters or {}
                forecast_record.tuned_parameters = {
                    **existing_tuned,
                    "xgboost": xgb_tuned_params,
                }

        # Step 3: Model selection & backtesting
        _check_cancelled(db, forecast_record)
        logger.info("Running backtests for forecast %s", forecast_id)

        best_metrics, comparison_rows, selection_details = backtest_and_select(
            processed,
            aggregation,
            candidates,
            sel_metric,
            cv_config,
            country=country,
            tuned_params=tuned_params,
            custom_holidays_df=custom_holidays_df,
            xgb_tuned_params=xgb_tuned_params,
        )
        selected_model = best_metrics["model"]
        forecast_record.selected_model = selected_model

        # Step 4: Train model
        _persist_forecast_progress(db, forecast_record, 3, "Training model")
        _check_cancelled(db, forecast_record)
        logger.info("Training %s for forecast %s", selected_model, forecast_id)
        if selected_model == "prophet":
            model, forecast_df = train_prophet_model(
                processed,
                horizon_days=horizon_days,
                country=country,
                tuned_params=tuned_params,
                custom_holidays_df=custom_holidays_df,
                aggregation=aggregation,
            )
        elif selected_model == "xgboost":
            from app.services.xgboost_model import train_xgb_model

            model, forecast_df = train_xgb_model(
                processed,
                horizon_days=horizon_days,
                country=country,
                custom_holidays_df=custom_holidays_df,
                xgb_params=xgb_tuned_params,
                aggregation=aggregation,
            )
        else:
            model, forecast_df = build_baseline_forecast_frame(
                processed, selected_model, horizon_days, aggregation
            )

        # Step 5: Trend changes
        trend_changes = []
        if selected_model == "prophet":
            trend_changes = detect_trend_changes(model, forecast_df)

        # Step 6: Store metrics
        for key in ["mape", "wape", "smape", "mase", "rmse", "mae"]:
            if key in best_metrics and best_metrics[key] is not None:
                setattr(forecast_record, key, best_metrics[key])

        forecast_record.data_start_date = df["date"].min().date()
        forecast_record.data_end_date = df["date"].max().date()
        forecast_record.data_row_count = len(df)
        forecast_record.seasonality_mode = (
            "multiplicative"
            if (
                df["quantity_sold"].std() / df["quantity_sold"].mean() > 0.5
                if df["quantity_sold"].mean() > 0
                else False
            )
            else "additive"
        )
        forecast_record.model_parameters = {
            **init_params,
            "candidates": [r["model"] for r in comparison_rows],
            "selectionMetric": selection_details.get("selectionMetricUsed"),
            "trendChanges": trend_changes,
            "demandProfile": demand_profile,
        }

        # Persist metrics + metadata now so the upcoming _check_cancelled
        # (which calls db.refresh) does not discard them.
        db.commit()

        # Step 7: Format frontend data
        frontend_data = format_frontend_data(
            processed, forecast_df, best_metrics, product.product_id, product.name
        )
        frontend_data["trendChanges"] = trend_changes
        frontend_data["selectedModel"] = selected_model
        frontend_data["demandProfile"] = demand_profile

        # Store forecast results (commit together so /results is not empty at this step)
        _check_cancelled(db, forecast_record)
        last_historical = processed["ds"].max()
        future_rows = forecast_df[forecast_df["ds"] > last_historical]
        result_records = []
        for _, row in future_rows.iterrows():
            result_records.append(
                ForecastResult(
                    forecast_id=forecast_record.id,
                    date=row["ds"].date(),
                    predicted_value=max(0, math.ceil(float(row["yhat"]))),
                    lower_bound_80=max(0, math.floor(float(row.get("yhat_lower", 0)))),
                    upper_bound_80=max(0, math.ceil(float(row.get("yhat_upper", row["yhat"])))),
                    trend=round(float(row.get("trend", 0)), 2)
                    if "trend" in row
                    else None,
                    weekly_seasonality=round(float(row.get("weekly", 0)), 2)
                    if "weekly" in row
                    else None,
                    yearly_seasonality=round(float(row.get("yearly", 0)), 2)
                    if "yearly" in row
                    else None,
                )
            )
        forecast_record.progress_step = 4
        forecast_record.progress_total = FORECAST_PROGRESS_TOTAL
        forecast_record.progress_label = "Saving forecast"
        db.add_all(result_records)
        db.commit()

        # Step 5: AI explanation (status already used by clients for this phase)
        _check_cancelled(db, forecast_record)
        forecast_record.progress_step = 5
        forecast_record.progress_total = FORECAST_PROGRESS_TOTAL
        forecast_record.progress_label = "Generating explanation"
        forecast_record.status = "generating_explanation"
        db.commit()

        try:
            explanation = generate_gemini_explanation(frontend_data, user=user)
            if explanation:
                import json

                forecast_record.ai_explanation = (
                    json.dumps(explanation)
                    if isinstance(explanation, dict)
                    else explanation
                )
        except Exception as e:
            logger.warning("Gemini explanation failed: %s", e)

        # Done!
        _clear_forecast_progress(db, forecast_record)
        forecast_record.status = "completed"
        db.commit()
        logger.info("Forecast %s completed successfully", forecast_id)

    except ForecastCancelledException:
        logger.info("Forecast %s pipeline aborted (cancelled by user)", forecast_id)
        # Status is already 'cancelled' — nothing more to do.

    except Exception as e:
        logger.error("Forecast %s failed: %s", forecast_id, e, exc_info=True)
        try:
            forecast_record = (
                db.query(Forecast).filter(Forecast.id == forecast_id).first()
            )
            if forecast_record and forecast_record.status != "cancelled":
                _clear_forecast_progress(db, forecast_record)
                forecast_record.status = "failed"
                forecast_record.error_message = str(e)
                db.commit()
        except Exception:
            logger.error("Failed to update forecast status to 'failed'")
