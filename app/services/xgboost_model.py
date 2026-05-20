"""
XGBoost Forecasting Model — for non-seasonal demand patterns.

Provides an alternative to Prophet for products that show weak or no
seasonality.  Uses lag features, rolling statistics, calendar indicators,
and optional holiday / weather regressors.

Key public functions
--------------------
- build_xgb_features      : feature engineering on a Prophet-style (ds, y) DataFrame
- backtest_xgb_model      : rolling-origin cross-validation (same folds as Prophet)
- train_xgb_model         : fit on the full training set and produce a forecast
- optuna_tune_xgboost     : Bayesian hyper-parameter optimisation via Optuna
"""

import logging
import math
from datetime import timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────

# Minimum number of rows required for XGBoost (needs lag_28 + at least
# a handful of training rows after dropping NaN lags).
MIN_ROWS_XGBOOST = 42

# Default hyper-parameters — tuned for typical retail demand data.
DEFAULT_XGB_PARAMS: dict = {
    "n_estimators": 200,
    "max_depth": 6,
    "learning_rate": 0.1,
    "min_child_weight": 3,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
}

# Feature columns produced by build_xgb_features (excluding weather).
_CALENDAR_FEATURES = [
    "day_of_week",
    "day_of_month",
    "month",
    "week_of_year",
    "is_weekend",
    "is_holiday",
]
_LAG_FEATURES = ["lag_7", "lag_14", "lag_28"]
_ROLLING_FEATURES = ["rolling_mean_7", "rolling_std_7", "rolling_mean_28"]


def _get_safe_value(lst: list, backward_offset: int, fallback_val: float = 0.0) -> float:
    try:
        if len(lst) >= abs(backward_offset):
            return float(lst[backward_offset])
        elif len(lst) > 0:
            return float(lst[-1])
        return fallback_val
    except Exception:
        return fallback_val


# ── Feature Engineering ───────────────────────────────────────


def _build_holiday_set(
    country: str | None,
    custom_holidays_df: pd.DataFrame | None,
    years: list[int],
) -> set:
    """Return a set of ``datetime.date`` objects for all holidays.

    Combines country-level holidays (from the *holidays* library) with
    any user-defined custom holidays.
    """
    holiday_dates: set = set()

    # Country holidays via the ``holidays`` package
    if country:
        try:
            import holidays as holidays_lib

            country_holidays = holidays_lib.country_holidays(country, years=years)
            holiday_dates.update(country_holidays.keys())
        except Exception as exc:
            logger.warning("Could not load holidays for %s: %s", country, exc)

    # Custom holidays from the DB
    if custom_holidays_df is not None and not custom_holidays_df.empty:
        for _, row in custom_holidays_df.iterrows():
            ds_val = row.get("ds")
            if ds_val is not None:
                if hasattr(ds_val, "date"):
                    holiday_dates.add(ds_val.date())
                else:
                    holiday_dates.add(pd.Timestamp(ds_val).date())

    return holiday_dates


def build_xgb_features(
    df: pd.DataFrame,
    country: str | None = None,
    custom_holidays_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Create feature columns for XGBoost from a Prophet-style DataFrame.

    Parameters
    ----------
    df : DataFrame
        Must contain at least ``ds`` (datetime) and ``y`` (numeric) columns.
        May also contain ``temperature`` and ``precipitation`` if weather
        data was merged during preprocessing.
    country : str, optional
        ISO-3166 country code for holiday calendar (e.g. ``"PH"``, ``"US"``).
    custom_holidays_df : DataFrame, optional
        Prophet-format custom holidays with ``ds`` column.

    Returns
    -------
    DataFrame
        Copy of *df* with additional feature columns appended.
    """
    feat = df.copy()
    feat["ds"] = pd.to_datetime(feat["ds"])

    # ── Calendar features ─────────────────────────────────────
    feat["day_of_week"] = feat["ds"].dt.dayofweek          # 0-6
    feat["day_of_month"] = feat["ds"].dt.day               # 1-31
    feat["month"] = feat["ds"].dt.month                    # 1-12
    feat["week_of_year"] = feat["ds"].dt.isocalendar().week.astype(int)
    feat["is_weekend"] = (feat["day_of_week"] >= 5).astype(int)

    # ── Holiday indicator ─────────────────────────────────────
    years = sorted(feat["ds"].dt.year.unique().tolist())
    holiday_set = _build_holiday_set(country, custom_holidays_df, years)
    feat["is_holiday"] = feat["ds"].dt.date.isin(holiday_set).astype(int)

    # ── Lag features ──────────────────────────────────────────
    feat["lag_7"] = feat["y"].shift(7)
    feat["lag_14"] = feat["y"].shift(14)
    feat["lag_28"] = feat["y"].shift(28)

    # ── Rolling statistics ────────────────────────────────────
    feat["rolling_mean_7"] = feat["y"].shift(1).rolling(window=7, min_periods=1).mean()
    feat["rolling_std_7"] = feat["y"].shift(1).rolling(window=7, min_periods=1).std().fillna(0)
    feat["rolling_mean_28"] = feat["y"].shift(1).rolling(window=28, min_periods=1).mean()

    # Weather columns (temperature, precipitation) are left as-is if
    # they already exist in ``df`` from preprocessing.

    return feat


def _get_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return the list of feature column names present in *df*."""
    base = _CALENDAR_FEATURES + _LAG_FEATURES + _ROLLING_FEATURES
    weather = [c for c in ("temperature", "precipitation") if c in df.columns]
    return base + weather


# ── Backtesting ───────────────────────────────────────────────


def backtest_xgb_model(
    df: pd.DataFrame,
    aggregation: str,
    cv_config: dict,
    country: str | None = None,
    custom_holidays_df: pd.DataFrame | None = None,
    xgb_params: dict | None = None,
) -> dict:
    """Rolling-origin backtest for XGBoost, using the same fold structure.

    Parameters
    ----------
    df : DataFrame
        Pre-processed Prophet-style DataFrame (``ds``, ``y``, optional
        weather columns).
    aggregation : str
        Time granularity (``"daily"`` / ``"weekly"`` / ``"monthly"``).
    cv_config : dict
        Must contain ``initial_days``, ``horizon_days``, ``period_days``.
    country, custom_holidays_df :
        Passed through to ``build_xgb_features``.
    xgb_params : dict, optional
        Overrides for XGBRegressor hyper-parameters.

    Returns
    -------
    dict
        Error metrics dict (same shape as other model backtest results).
    """
    from xgboost import XGBRegressor

    from app.services.forecast_service import (
        _generate_backtest_folds,
        compute_error_metrics,
    )

    params = {**DEFAULT_XGB_PARAMS, **(xgb_params or {})}

    # Build features on the full dataset first
    feat_df = build_xgb_features(df, country=country, custom_holidays_df=custom_holidays_df)
    feature_cols = _get_feature_columns(feat_df)

    folds = _generate_backtest_folds(df, cv_config)
    if not folds:
        from app.core.exceptions import ForecastFailedException

        raise ForecastFailedException("Unable to generate backtest folds for XGBoost")

    y_true_all: list[float] = []
    y_pred_all: list[float] = []

    for cutoff, horizon_end in folds:
        train_mask = feat_df["ds"] <= cutoff
        test_mask = (feat_df["ds"] > cutoff) & (feat_df["ds"] <= horizon_end)

        train = feat_df[train_mask].dropna(subset=_LAG_FEATURES)
        test = feat_df[test_mask]

        if train.empty or test.empty:
            continue

        # Ensure test rows have lag features (they will if we computed
        # features on the full dataset).
        test_clean = test.dropna(subset=_LAG_FEATURES)
        if test_clean.empty:
            continue

        X_train = train[feature_cols].fillna(0)
        y_train = train["y"]
        X_test = test_clean[feature_cols].fillna(0)

        model = XGBRegressor(**params)
        model.fit(X_train, y_train, verbose=False)

        preds = model.predict(X_test)
        preds = np.clip(preds, 0, None)  # Non-negative

        y_true_all.extend(test_clean["y"].to_numpy(dtype=float))
        y_pred_all.extend(preds.astype(float))

    metrics = compute_error_metrics(
        y_true_all, y_pred_all, df["y"].to_numpy(dtype=float)
    )
    metrics["model"] = "xgboost"
    metrics["folds"] = len(folds)
    return metrics


# ── Optuna Hyper-Parameter Tuning ─────────────────────────────


def optuna_tune_xgboost(
    df: pd.DataFrame,
    aggregation: str,
    cv_config: dict,
    country: str | None = None,
    custom_holidays_df: pd.DataFrame | None = None,
    n_trials: int = 30,
) -> dict | None:
    """Use Optuna to find optimal XGBoost hyper-parameters.

    Searches over:
    - n_estimators          : 50 – 500
    - max_depth             : 3 – 10
    - learning_rate         : 0.01 – 0.3
    - min_child_weight      : 1 – 10
    - subsample             : 0.6 – 1.0
    - colsample_bytree      : 0.6 – 1.0
    - reg_alpha             : 1e-3 – 10
    - reg_lambda            : 1e-3 – 10

    Each trial runs a full rolling back-test and evaluates MAPE.
    Returns the best parameter dict, or ``None`` if tuning fails.
    """
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.warning("Optuna not installed — skipping XGBoost tuning")
        return None

    logger.info("Starting Optuna XGBoost tuning (%d trials)...", n_trials)

    def objective(trial: "optuna.Trial") -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 50, 500),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            "random_state": 42,
        }

        try:
            metrics = backtest_xgb_model(
                df,
                aggregation,
                cv_config,
                country=country,
                custom_holidays_df=custom_holidays_df,
                xgb_params=params,
            )
            mape = metrics.get("mape")
            if mape is None:
                return float("inf")
            return mape
        except Exception as e:
            logger.debug("Optuna XGBoost trial failed: %s", e)
            return float("inf")

    try:
        study = optuna.create_study(direction="minimize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

        best_params = study.best_params
        best_params["random_state"] = 42
        best_value = study.best_value
        logger.info(
            "Optuna XGBoost tuning complete — best MAPE: %.2f%%, params: %s",
            best_value,
            best_params,
        )
        return best_params

    except Exception as e:
        logger.warning("Optuna XGBoost tuning failed: %s", e)
        return None


# ── Training & Forecasting ────────────────────────────────────


def train_xgb_model(
    df: pd.DataFrame,
    horizon_days: int = 90,
    country: str | None = None,
    custom_holidays_df: pd.DataFrame | None = None,
    xgb_params: dict | None = None,
    aggregation: str = "daily",
) -> tuple[dict, pd.DataFrame]:
    """Train XGBoost on full data and produce an aligned recursive multi-step forecast."""
    from xgboost import XGBRegressor

    params = {**DEFAULT_XGB_PARAMS, **(xgb_params or {})}

    feat_df = build_xgb_features(df, country=country, custom_holidays_df=custom_holidays_df)
    feature_cols = _get_feature_columns(feat_df)

    train = feat_df.dropna(subset=_LAG_FEATURES).copy()
    if len(train) < 5:
        from app.core.exceptions import ForecastFailedException

        raise ForecastFailedException(
            f"Not enough data for XGBoost after lag feature creation "
            f"({len(train)} rows, need ≥5)"
        )

    X_train = train[feature_cols].fillna(0)
    y_train = train["y"]

    logger.info("Training XGBoost model (%d rows, %d features)...", len(X_train), len(feature_cols))
    model = XGBRegressor(**params)
    model.fit(X_train, y_train, verbose=False)

    train_preds = model.predict(X_train)
    residuals = y_train.values - train_preds
    residual_std = float(np.std(residuals)) if len(residuals) > 1 else 0.0

    historical_yhat = np.full(len(df), np.nan)
    train_indices = train.index
    fitted = model.predict(X_train)
    for i, idx in enumerate(train_indices):
        pos = df.index.get_loc(idx)
        historical_yhat[pos] = fitted[i]

    freq_map = {"daily": "D", "weekly": "W", "monthly": "MS"}
    freq_str = freq_map.get(aggregation, "D")
    periods = int(math.ceil(horizon_days / 7.0)) if aggregation == "weekly" else (
              int(math.ceil(horizon_days / 30.44)) if aggregation == "monthly" else horizon_days)

    last_date = df["ds"].max()
    future_dates = pd.date_range(
        start=last_date,
        periods=periods + 1,
        freq=freq_str,
    )[1:]

    recent_values = list(df["y"].values)

    future_years = sorted(set(d.year for d in future_dates))
    all_years = sorted(set(df["ds"].dt.year.unique().tolist()) | set(future_years))
    holiday_set = _build_holiday_set(country, custom_holidays_df, all_years)

    has_weather = "temperature" in feat_df.columns and "precipitation" in feat_df.columns
    future_preds: list[float] = []

    for date in future_dates:
        row_features: dict = {}

        row_features["day_of_week"] = date.dayofweek
        row_features["day_of_month"] = date.day
        row_features["month"] = date.month
        row_features["week_of_year"] = int(date.isocalendar()[1])
        row_features["is_weekend"] = int(date.dayofweek >= 5)
        row_features["is_holiday"] = int(date.date() in holiday_set)

        row_features["lag_7"] = _get_safe_value(recent_values, -7)
        row_features["lag_14"] = _get_safe_value(recent_values, -14)
        row_features["lag_28"] = _get_safe_value(recent_values, -28)

        last_7 = recent_values[-7:] if len(recent_values) >= 7 else recent_values
        last_28 = recent_values[-28:] if len(recent_values) >= 28 else recent_values

        row_features["rolling_mean_7"] = float(np.mean(last_7)) if last_7 else 0.0
        row_features["rolling_std_7"] = float(np.std(last_7)) if len(last_7) > 1 else 0.0
        row_features["rolling_mean_28"] = float(np.mean(last_28)) if last_28 else 0.0

        if has_weather:
            weather_row = feat_df[feat_df["ds"] == date]
            if not weather_row.empty:
                row_features["temperature"] = float(weather_row["temperature"].iloc[0])
                row_features["precipitation"] = float(weather_row["precipitation"].iloc[0])
            else:
                row_features["temperature"] = float(feat_df["temperature"].iloc[-1]) if len(feat_df) > 0 else 0.0
                row_features["precipitation"] = float(feat_df["precipitation"].iloc[-1]) if len(feat_df) > 0 else 0.0

        X_row = pd.DataFrame([row_features])[feature_cols].fillna(0)
        pred = float(model.predict(X_row)[0])
        pred = max(0.0, pred)

        future_preds.append(pred)
        recent_values.append(pred)

    hist_part = pd.DataFrame({
        "ds": df["ds"],
        "yhat": np.where(np.isnan(historical_yhat), 0.0, historical_yhat),
    })

    future_preds_arr = np.array(future_preds, dtype=float)
    future_part = pd.DataFrame({
        "ds": future_dates,
        "yhat": future_preds_arr,
        "yhat_lower": np.maximum(0, future_preds_arr - 1.28 * residual_std),
        "yhat_upper": future_preds_arr + 1.28 * residual_std,
    })

    hist_part["yhat_lower"] = np.maximum(0, hist_part["yhat"] - 1.28 * residual_std)
    hist_part["yhat_upper"] = hist_part["yhat"] + 1.28 * residual_std

    forecast_df = pd.concat([hist_part, future_part], ignore_index=True)

    model_info = {
        "model_name": "xgboost",
        "params": params,
        "n_features": len(feature_cols),
        "feature_columns": feature_cols,
        "residual_std": round(residual_std, 4),
        "training_rows": len(train),
    }

    logger.info("Generated %d-period XGBoost forecast using frequency %s", periods, freq_str)
    return model_info, forecast_df


# ── Seasonality Strength Detection ────────────────────────────


def detect_seasonality_strength(values: np.ndarray, lag: int = 7) -> float | None:
    """Compute the autocorrelation at a given lag to measure seasonality.

    Returns a float in [-1, 1] (Pearson autocorrelation at *lag*),
    or ``None`` if there is insufficient data.

    A value close to 0 indicates weak or no seasonality at that period,
    suggesting XGBoost may outperform Prophet.
    """
    if len(values) < lag * 2:
        return None

    series = pd.Series(values, dtype=float)
    autocorr = series.autocorr(lag=lag)

    if autocorr is None or np.isnan(autocorr):
        return None

    return float(autocorr)
