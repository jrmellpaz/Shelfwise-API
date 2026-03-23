# Forecasting Pipeline — Backend

An end-to-end sales forecasting pipeline that takes raw CSV data, validates and cleans it, trains a Prophet model, evaluates accuracy, and generates plain-English business insights with Gemini AI.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up your Gemini API key
cp .env.example .env
# Edit .env and add your key from https://aistudio.google.com/apikey

# 3. Generate test data
python generate_sample_data.py

# 4. Run the pipeline
python pipeline_test.py --csv sample_sales_data.csv --product SKU-001
```

---

## Pipeline Steps

| Step | Description                                                                                                            |
| ---- | ---------------------------------------------------------------------------------------------------------------------- |
| 1    | **Load CSV** — Read and validate file size/row limits                                                                  |
| 2    | **Validate Structure** — Check columns, clean nulls, fix types                                                         |
| 3    | **Data Quality Assessment** — Score data health (0–100)                                                                |
| 3.5  | **Weather Data** _(optional)_ — Fetch from Open-Meteo API                                                              |
| 4    | **Preprocess** — Fill gaps with a chosen strategy, handle outliers, merge optional regressors, prepare for forecasting |
| 5.5  | **Hyperparameter Tuning** _(optional)_ — Optuna optimization                                                           |
| 5.6  | **Model Backtesting** _(optional)_ — Compare Prophet and baseline models on the same rolling windows                   |
| 6    | **Train Selected Model** — Fit Prophet or the best baseline/intermittent model                                         |
| 6.5  | **Trend Detection** — Identify significant trend changes                                                               |
| 7    | **Cross-Validation** — Calculate MAPE, WAPE, sMAPE, MASE, RMSE, MAE                                                    |
| 8    | **Format for Frontend** — Structure JSON for charting                                                                  |
| 9    | **Gemini Explanation** — AI-generated business insights                                                                |
| 10   | **Output** — Save results as JSON                                                                                      |

---

## Test Commands

### Generate Sample Data

```bash
# Default: ~18 months of data, 7 products, all edge cases
python generate_sample_data.py

# Custom output path
python generate_sample_data.py --output my_data.csv

# More history (2 years)
python generate_sample_data.py --days 730

# Clean data (no edge cases)
python generate_sample_data.py --no-duplicates --no-edge-cases
```

**Data Generator Options:**

| Flag              | Default                 | Description                                                                                   |
| ----------------- | ----------------------- | --------------------------------------------------------------------------------------------- |
| `--output`        | `sample_sales_data.csv` | Output CSV file path                                                                          |
| `--days`          | `548` (~18 months)      | Days of history to generate                                                                   |
| `--no-duplicates` | off                     | Skip duplicate row injection                                                                  |
| `--no-edge-cases` | off                     | Skip all edge case injection (nulls, type mismatches, negatives, future dates, extra columns) |

### Run the Forecasting Pipeline

```bash
# Forecast a single product
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001

# Forecast multiple products
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001,SKU-003

# Forecast all products in the dataset
python pipeline_test.py --csv test_edge_cases.csv --all

# Skip AI explanation (faster, no API key needed)
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --skip-gemini

# Change forecast horizon (default: 90 days)
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --horizon 180

# Enable hyperparameter tuning (slower but more accurate)
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --tune

# Tune with more trials
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --tune --tune-trials 50

# Re-tune from scratch (ignore cached parameters)
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --tune --no-cache

# Enable weather regressors (requires internet)
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --weather --latitude 14.5995 --longitude 120.9842

# Custom location for weather data
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --weather --latitude 10.3157 --longitude 123.8854

# Use built-in country holidays only when you explicitly want them
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --country US

# Add user-supplied holidays or store events
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --holidays-csv holidays.csv --holiday-date-col date --holiday-name-col event_name

# Add optional regressors like promos, payday flags, or stockout flags
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --regressors-csv regressors.csv --regressor-date-col date --regressor-cols promo,payday,stockout

# Change how missing dates are filled before training
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --gap-fill zero

# Control how outliers are handled
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --outlier-method none

# Customize the backtest windows
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --cv-initial-days 180 --cv-horizon-days 14 --cv-period-days 14

# Compare multiple models and auto-pick the best one
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --model-candidates prophet,naive,seasonal_naive,croston_sba --auto-select-model

# Let the pipeline detect demand type and choose candidates automatically
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --auto-select-model

# Intermittent-demand example for luxury / slow-selling products
python pipeline_test.py --csv slow.csv --product 221 --col-id item_id --col-date sale_date --col-qty total_items_sold --gap-fill zero --auto-select-model --skip-gemini

# Weekly aggregation instead of daily
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --aggregation weekly

# Use a different Gemini model
python pipeline_test.py --csv test_edge_cases.csv --product SKU-001 --gemini-model gemini-2.0-flash

# Map custom CSV column names if your data differs from the defaults
python pipeline_test.py --csv custom_sales.csv --col-date "Order Date" --col-id "SKU" --col-name "Item Title" --col-qty "Units"
```

**Pipeline Options:**

| Flag                         | Default                  | Description                                                                                                             |
| ---------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `--csv`                      | _(required)_             | Path to the sales CSV file                                                                                              |
| `--product`                  | first product            | Product ID(s), comma-separated                                                                                          |
| `--all`                      | off                      | Forecast all products in the dataset                                                                                    |
| `--horizon`                  | `90`                     | Forecast horizon in days                                                                                                |
| `--country`                  | off                      | Optional country code for Prophet's built-in holidays                                                                   |
| `--aggregation`              | `daily`                  | Data aggregation: `daily`, `weekly`, or `monthly`                                                                       |
| `--gap-fill`                 | `interpolate`            | Missing-date fill strategy: `interpolate`, `zero`, or `ffill`                                                           |
| `--outlier-method`           | `cap`                    | Outlier handling strategy: `cap`, `remove`, or `none`                                                                   |
| `--outlier-iqr-multiplier`   | `1.5`                    | IQR multiplier used to detect outliers                                                                                  |
| `--skip-gemini`              | off                      | Skip the Gemini AI explanation step                                                                                     |
| `--gemini-model`             | `gemini-3-flash-preview` | Which Gemini model to use                                                                                               |
| `--weather`                  | off                      | Enable weather regressors (Open-Meteo)                                                                                  |
| `--latitude`                 | off                      | Location latitude for weather data. Required with `--weather`                                                           |
| `--longitude`                | off                      | Location longitude for weather data. Required with `--weather`                                                          |
| `--tune`                     | off                      | Enable Optuna hyperparameter tuning                                                                                     |
| `--tune-trials`              | `30`                     | Number of tuning trials                                                                                                 |
| `--no-cache`                 | off                      | Ignore cached tuned parameters                                                                                          |
| `--holidays-csv`             | off                      | CSV of custom holidays or business events                                                                               |
| `--holiday-date-col`         | `ds`                     | Date column in the holidays CSV                                                                                         |
| `--holiday-name-col`         | `holiday`                | Event-name column in the holidays CSV                                                                                   |
| `--holiday-product-col`      | off                      | Optional product column in the holidays CSV                                                                             |
| `--holiday-lower-window-col` | off                      | Optional lower window column in the holidays CSV                                                                        |
| `--holiday-upper-window-col` | off                      | Optional upper window column in the holidays CSV                                                                        |
| `--regressors-csv`           | off                      | CSV of external regressors such as promos or payday flags                                                               |
| `--regressor-date-col`       | `date`                   | Date column in the regressors CSV                                                                                       |
| `--regressor-product-col`    | off                      | Optional product column in the regressors CSV                                                                           |
| `--regressor-cols`           | all inferred             | Comma-separated regressor columns to use                                                                                |
| `--cv-initial-days`          | auto                     | Initial training window for rolling backtests                                                                           |
| `--cv-horizon-days`          | auto                     | Forecast horizon for rolling backtests                                                                                  |
| `--cv-period-days`           | auto                     | Step size between backtest folds                                                                                        |
| `--model-candidates`         | `auto`                   | Comma-separated models to evaluate, or `auto` for dataset-driven candidate selection                                    |
| `--auto-select-model`        | off                      | Backtest all candidate models and choose the best one automatically                                                     |
| `--selection-metric`         | `auto`                   | Metric used to choose the winning model. `auto` uses `mase` for intermittent/lumpy/all_zero demand and `wape` otherwise |
| `--no-auto-detect-models`    | off                      | Disable automatic demand-profile based candidate detection                                                              |
| `--col-date`                 | `date`                   | CSV column name for date                                                                                                |
| `--col-id`                   | `product_id`             | CSV column name for product ID                                                                                          |
| `--col-name`                 | `product_name`           | CSV column name for product name                                                                                        |
| `--col-qty`                  | `quantity_sold`          | CSV column name for quantity sold                                                                                       |

---

## Custom Input Files

### Holidays CSV

You can now provide your own holidays or business-event dates instead of relying on placeholder data.

Minimum columns:

```csv
holiday,ds
Store Anniversary,2025-06-15
Year End Sale,2025-12-28
```

Optional columns:

- `product_id`: apply an event only to one product
- `lower_window`: number of days before the event to include
- `upper_window`: number of days after the event to include

Example:

```csv
holiday,ds,product_id,lower_window,upper_window
Store Anniversary,2025-06-15,SKU-001,0,2
Promo Weekend,2025-11-11,,0,0
```

### Regressors CSV

Use regressors when you already know about business drivers such as:

- promo days
- payday flags
- stockout flags
- campaign periods
- branch closure flags

Minimum columns:

```csv
date,promo,payday
2025-01-01,0,1
2025-01-02,1,0
```

Optional product-specific version:

```csv
date,product_id,promo,payday,stockout
2025-01-01,SKU-001,0,1,0
2025-01-02,SKU-001,1,0,0
```

Notes:

- If a regressor CSV is provided, all non-date and non-product columns are treated as regressors unless you limit them with `--regressor-cols`.
- Missing regressor values are filled with `0`.
- If you want regressors to influence the future forecast horizon, include future dates in the regressor CSV too.

---

## Model Selection

The pipeline can now compare multiple forecasting strategies on the same rolling backtest windows.
It can also inspect each product's demand pattern and choose sensible candidate models automatically.

Supported models:

- `prophet`: best when the product has stable trend and seasonality patterns
- `naive`: predicts the next values from the latest observed value only
- `seasonal_naive`: repeats the most recent seasonal pattern
- `croston_sba`: designed for intermittent demand where many days have zero sales

Automatic demand detection:

The pipeline computes these series characteristics per product:

- `ADI` (average demand interval): how many periods typically pass between non-zero sales
- `CV²`: how volatile the non-zero demand sizes are
- `zeroRatio`: share of periods with zero sales

It then classifies the product as one of these patterns:

- `smooth`: frequent sales with relatively stable demand sizes
- `erratic`: frequent sales but volatile demand sizes
- `intermittent`: many zero-sale periods but non-zero sales are fairly stable
- `lumpy`: many zero-sale periods and volatile non-zero sales

Candidate selection defaults:

- `smooth` -> `prophet`, `seasonal_naive`, `naive`
- `erratic` -> `prophet`, `naive`, `seasonal_naive`
- `intermittent` -> `croston_sba`, `naive`, `prophet`
- `lumpy` -> `croston_sba`, `naive`, `prophet`

Recommended usage:

- Dense daily sales: `--auto-select-model`
- Intermittent luxury-store items: `--gap-fill zero --auto-select-model`
- Manual override: pass `--model-candidates ... --no-auto-detect-models`

Selection metric defaults:

- `--selection-metric auto` picks `mase` for `intermittent`, `lumpy`, and `all_zero` demand because percentage metrics become unstable when many days have zero sales.
- `--selection-metric auto` picks `wape` for `smooth` and `erratic` demand because it stays easy to interpret for denser series.
- The output JSON stores both the requested metric and the effective metric under `modelSelection`.
- When tuning is enabled, the pipeline records both pre-tuning and post-tuning model comparisons so you can see whether tuning changed the winner.
- The pipeline also reports winner margin and fold-stability diagnostics, so model choice is based on both average score and consistency.

Backtest window controls:

- `--cv-initial-days`: how much history to train on before the first test window
- `--cv-horizon-days`: how far ahead each test window predicts
- `--cv-period-days`: how much the window moves forward each round

Example:

```bash
python pipeline_test.py --csv slow.csv --product 221 --col-id item_id --col-date sale_date --col-qty total_items_sold --gap-fill zero --cv-initial-days 365 --cv-horizon-days 30 --cv-period-days 30 --model-candidates prophet,croston_sba,naive --auto-select-model --skip-gemini
```

---

## Test Products

The data generator creates 7 product archetypes designed to test different pipeline behaviors:

| Product ID | Name                   | Archetype       | What It Tests                   |
| ---------- | ---------------------- | --------------- | ------------------------------- |
| SKU-001    | Standard Widget        | Steady          | Stable sales, baseline accuracy |
| SKU-002    | Premium Gadget         | Growth          | Upward trend detection          |
| SKU-003    | Legacy Component       | Declining       | Downward trend detection        |
| SKU-004    | Holiday Gift Set       | Seasonal        | Strong yearly patterns          |
| SKU-005    | Experimental Accessory | Volatile        | High noise, outlier robustness  |
| SKU-006    | New Launch Item        | New (~3 months) | Short history warnings          |
| SKU-007    | Discontinued Item      | Zero Sales      | Zero-activity handling          |

### Edge Cases Injected

- Missing dates (gaps in time series)
- Random outliers (unusually high/low sales)
- Duplicate rows
- NaN/null values in `date` and `quantity_sold`
- Type mismatches (strings like `"N/A"`, `"unknown"` in numeric columns)
- Negative quantity values
- Future-dated rows
- Extra unexpected columns (`notes`)

---

## Output

The pipeline outputs one JSON file per product: `forecast_output_<PRODUCT_ID>.json`

Each file contains:

| Field            | Description                                                                                        |
| ---------------- | -------------------------------------------------------------------------------------------------- |
| `historical[]`   | Daily actual sales (for chart plotting)                                                            |
| `forecast[]`     | Predicted values with upper/lower bounds                                                           |
| `components`     | Trend, weekly, and yearly decomposition                                                            |
| `metrics`        | MAPE, WAPE, sMAPE, MASE, RMSE, MAE with ratings                                                    |
| `trendChanges[]` | Detected trend shift points                                                                        |
| `selectedModel`  | Which model was used for the final forecast                                                        |
| `demandProfile`  | Detected demand type plus a plain-English summary                                                  |
| `modelSelection` | Candidate comparison, pre/post-tune diagnostics, winner margin, and plain-English selection reason |
| `dataHealth`     | Data quality scorecard (0–100)                                                                     |
| `tuning`         | Best hyperparameters (if tuning was enabled)                                                       |
| `explanation`    | Gemini AI-generated business insights                                                              |

---

## Environment Setup

### `.env` File

```env
GEMINI_API_KEY=your-gemini-api-key-here
```

Get your API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### Dependencies

```
prophet>=1.1.0
pandas>=2.0.0
numpy>=1.24.0
google-genai>=1.0.0
python-dotenv>=1.0.0
requests>=2.31.0
optuna>=4.0.0
matplotlib>=3.7.0
```

Install all dependencies:

```bash
pip install -r requirements.txt
```

---

## File Structure

```
backend/
├── .env                  # Your API key (git-ignored)
├── .env.example          # Template for .env
├── generate_sample_data.py   # Synthetic data generator
├── pipeline_test.py          # Main forecasting pipeline
├── requirements.txt          # Python dependencies
├── test_edge_cases.csv       # Pre-generated test data
├── tuned_params_cache.json   # Cached hyperparameters
└── forecast_output_*.json    # Pipeline output files
```
