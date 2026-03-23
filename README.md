# ShelfWise Inventory Forecasting API

A FastAPI-powered backend for the **ShelfWise** AI-driven inventory forecasting system. It enables businesses to upload historical sales data (CSV), run multi-model demand forecasting pipelines, and receive AI-generated explanations of the results — all through a RESTful API with JWT authentication.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [API Reference](#api-reference)
- [Forecasting Pipeline](#forecasting-pipeline)
- [Environment Variables](#environment-variables)
- [Setup & Installation](#setup--installation)
- [Running the Server](#running-the-server)
- [CSV Upload Format](#csv-upload-format)
- [Response Format](#response-format)
- [Request Flow (Client ↔ API)](#request-flow-client--api)
- [Testing](#testing)
- [Security](#security)

---

## Overview

ShelfWise provides small-to-medium businesses with an automated demand forecasting solution. Users upload their historical sales CSVs, and the backend:

1. **Validates & profiles** the uploaded data
2. **Classifies demand** using the ADI/CV² framework (smooth, erratic, intermittent, lumpy)
3. **Backtests multiple models** (Prophet, Croston SBA, Naive, Seasonal Naive) using rolling cross-validation
4. **Selects the best model** automatically based on the demand profile and error metrics (MAPE, WAPE, MASE, etc.)
5. **Generates a forecast** for a user-specified horizon (default: 90 days)
6. **Produces an AI explanation** of the forecast via Google Gemini

Forecasts run asynchronously: the API returns immediately with a job ID, and the result is stored in the database when ready.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | [FastAPI](https://fastapi.tiangolo.com/) |
| ASGI Server | [Uvicorn](https://www.uvicorn.org/) |
| ORM | [SQLAlchemy](https://www.sqlalchemy.org/) |
| Database | PostgreSQL (via `psycopg2-binary`) |
| Migrations | [Alembic](https://alembic.sqlalchemy.org/) |
| Configuration | [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) |
| Authentication | JWT (`python-jose`) + `passlib[bcrypt]` |
| Rate Limiting | [SlowAPI](https://github.com/laurentS/slowapi) |
| Forecasting | [Prophet](https://facebook.github.io/prophet/) |
| Data Science | pandas, NumPy |
| Hyperparameter Tuning | [Optuna](https://optuna.org/) |
| AI Explanations | [Google Gemini API](https://ai.google.dev/) (`google-genai`) |
| Weather Regressors | [Open-Meteo](https://open-meteo.com/) (optional) |

---

## Project Structure

```
shelfwise-api/
├── .env                        # Environment variables (never commit to version control)
├── requirements.txt            # Python dependencies
├── tests/                      # Pytest unit tests + live E2E script (`test_api.py`)
├── alembic.ini                 # Alembic migration configuration
├── alembic/                    # Database migrations
│   ├── env.py                  # Migration environment (reads DATABASE_URL from settings)
│   ├── script.py.mako          # Migration script template
│   └── versions/               # Auto-generated migration scripts
├── references/                 # Documentation and reference materials
│   ├── BACKEND_REFERENCE.md
│   ├── README.md
│   └── pipeline_test.py        # Original prototype pipeline script
│
└── app/                        # Application package
    ├── main.py                 # FastAPI app factory: middleware, routers, error handlers
    ├── config.py               # Pydantic Settings — reads from .env
    ├── database.py             # SQLAlchemy engine, session factory, Base
    ├── dependencies.py         # Reusable FastAPI dependencies (e.g., get_current_user)
    │
    ├── api/
    │   └── v1/
    │       ├── router.py       # Aggregates all sub-routers under /api/v1
    │       ├── auth.py         # POST /register, /login, /refresh, /logout; GET /me
    │       ├── upload.py       # POST /upload/, /validate, /confirm; GET /upload/template
    │       ├── forecasts.py    # POST /forecasts; GET /forecasts, /{id}, /{id}/results, /{id}/components, exports
    │       ├── products.py     # GET, PATCH /products; PATCH /products/{id}/archive
    │       ├── dashboard.py    # GET /dashboard (quick stats + recent forecasts)
    │       ├── profile.py      # GET/PATCH /profile; PUT /profile/password; GET/PUT /profile/holidays
    │       ├── shared.py       # GET /shared/forecasts/{token} (public, no auth)
    │       └── health.py       # GET /health (system health check)
    │
    ├── core/
    │   ├── exceptions.py       # Custom exception classes (AppException, NotFoundException, etc.)
    │   ├── logging.py          # Logging setup
    │   └── security.py         # JWT creation/decoding, bcrypt password hashing
    │
    ├── middleware/
    │   ├── error_handler.py    # Global exception handlers (AppException, unhandled errors)
    │   └── activity_logging.py # Automatic request-level activity logging middleware
    │
    ├── models/                 # SQLAlchemy ORM models
    │   ├── user.py             # Users table
    │   ├── product.py          # Products table
    │   ├── sales_data.py       # Sales data table
    │   ├── forecast.py         # Forecasts table (metadata + metrics)
    │   ├── forecast_result.py  # Forecast result data points table
    │   ├── activity_log.py     # Activity logs table (user action audit trail)
    │   └── csv_upload_session.py  # Pending CSV upload sessions (BYTEA + column_map)
    │
    ├── schemas/                # Pydantic request/response schemas
    │   ├── auth.py             # RegisterRequest, LoginRequest, TokenResponse, UserResponse
    │   ├── base.py             # Shared base schema config
    │   ├── common.py           # ApiResponse, paginated_response, success_response helpers
    │   └── forecast.py         # ForecastRequest, UploadValidateRequest, UploadConfirmRequest, etc.
    │
    └── services/               # Business logic layer
        ├── csv_service.py      # CSV parsing, validation, quality scoring, DB commit
        ├── upload_session_service.py  # Persisted csv_upload_sessions (multi-worker safe)
        ├── forecast_service.py # Core forecasting pipeline (preprocessing → tuning → model selection → training)
        ├── gemini_service.py   # Google Gemini API integration for AI explanations
        ├── export_service.py   # Forecast export generation (CSV, chart PNG, PDF report)
        └── activity_logger.py  # Non-blocking background task logger for user actions
```

---

## Database Schema

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | Auto-generated |
| `email` | String | Unique, lowercase |
| `password_hash` | String | bcrypt hash |
| `business_name` | String | |
| `contact_email` | String | Optional |
| `mobile_number` | String | Optional |
| `business_logo` | String | Optional URL/path |
| `default_forecast_period` | Integer | In days |
| `default_confidence_level` | String | `'80'`, `'95'`, or `'both'` |
| `holiday_calendar` | String | ISO country code (e.g., `'PH'`) |
| `created_at` | Timestamp | Server default |

### `products`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | Auto-generated |
| `user_id` | UUID (FK → users) | CASCADE delete |
| `product_id` | String | SKU from CSV |
| `name` | String | From CSV `product_name` |
| `category` | String | User-editable metadata |
| `description` | Text | User-editable metadata |
| `notes` | Text | User-editable metadata |
| `is_archived` | Boolean | Default `false` |
| `created_at` | Timestamp | |
| `updated_at` | Timestamp | Auto-updated |

### `sales_data`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID (FK → users) | |
| `product_id` | UUID (FK → products) | |
| `date` | Date | |
| `quantity_sold` | Float | |
| `created_at` | Timestamp | |

### `csv_upload_sessions`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | Returned to the client as **`uploadSessionId`** |
| `user_id` | UUID (FK → users) | Owner; CASCADE delete |
| `filename` | String | Original upload name |
| `raw_bytes` | BYTEA | Full CSV (max size enforced before insert) |
| `stage` | String | `uploaded` or `validated` |
| `column_map` | JSONB | Set after validate; used to replay parse on confirm |
| `created_at` | Timestamp | |
| `expires_at` | Timestamp | TTL (`UPLOAD_SESSION_TTL_HOURS`) |

### `forecasts`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID (FK → users) | |
| `product_id` | UUID (FK → products) | |
| `forecast_date` | Timestamp | When forecast was requested |
| `forecast_horizon` | Integer | Days ahead to forecast |
| `time_granularity` | String | `daily`, `weekly`, `monthly` |
| `confidence_level` | String | `'80'`, `'95'`, `'both'` |
| `seasonality_mode` | String | `additive` or `multiplicative` |
| `selected_model` | String | e.g., `prophet`, `croston_sba` |
| `demand_profile` | String | `smooth`, `erratic`, `intermittent`, `lumpy` |
| `status` | String | `processing` → `generating_explanation` → `completed` / `failed` |
| `mape` | Float | Mean Absolute Percentage Error |
| `wape` | Float | Weighted APE |
| `smape` | Float | Symmetric MAPE |
| `mase` | Float | Mean Absolute Scaled Error |
| `rmse` | Float | Root Mean Square Error |
| `mae` | Float | Mean Absolute Error |
| `data_start_date` | Date | |
| `data_end_date` | Date | |
| `data_row_count` | Integer | |
| `model_parameters` | JSONB | Default Prophet params |
| `tuned_parameters` | JSONB | Optuna-tuned params |
| `ai_explanation` | Text | Gemini-generated summary |
| `error_message` | Text | Populated on failure |
| `created_at` | Timestamp | |

### `forecast_results`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `forecast_id` | UUID (FK → forecasts) | CASCADE delete |
| `date` | Date | |
| `predicted_value` | Float | |
| `lower_bound_80` | Float | |
| `upper_bound_80` | Float | |
| `lower_bound_95` | Float | |
| `upper_bound_95` | Float | |
| `trend` | Float | Prophet trend component |
| `weekly_seasonality` | Float | Prophet weekly component |
| `yearly_seasonality` | Float | Prophet yearly component |

---

## API Reference

All endpoints are prefixed with `/api/v1`. Interactive docs are available at `/docs` (Swagger UI) and `/redoc`.

### Authentication — `/api/v1/auth`

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `POST` | `/auth/register` | No | Create a new user account |
| `POST` | `/auth/login` | No | Authenticate and get token pair |
| `POST` | `/auth/refresh` | No | Exchange refresh token for new access token |
| `POST` | `/auth/logout` | Yes | Acknowledge client-side logout |
| `GET` | `/auth/me` | Yes | Get current user info |

### Upload — `/api/v1/upload`

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `POST` | `/upload/` | Yes | Upload CSV; returns column detection, suggested mappings, and **`uploadSessionId`** |
| `POST` | `/upload/validate` | Yes | Apply `columnMap` to the session’s file; returns quality preview (does not commit) |
| `POST` | `/upload/confirm` | Yes | Commit validated data; body must include **`uploadSessionId`** and optional **`skipProductIds`** |
| `GET` | `/upload/template` | No | Download a sample CSV template |

> **Three-step upload:** (1) `POST /upload/` stores the file in a server-side session and returns **`uploadSessionId`**. (2) `POST /upload/validate` sends **`uploadSessionId`** + **`columnMap`**. (3) `POST /upload/confirm` sends **`uploadSessionId`** (and optional skips) to write `sales_data`. Sessions expire after `UPLOAD_SESSION_TTL_HOURS` (default 24). See [references/FRONTEND_INTEGRATION.md](references/FRONTEND_INTEGRATION.md) for client patterns.

### Products — `/api/v1/products`

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `GET` | `/products/` | Yes | List all products (paginated, filterable by category/archived status) |
| `GET` | `/products/{id}` | Yes | Get a single product's details |
| `PATCH` | `/products/{id}` | Yes | Update metadata (category, description, notes) |
| `PATCH` | `/products/{id}/archive` | Yes | Toggle archive/unarchive status |

### Forecasts — `/api/v1/forecasts`

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `POST` | `/forecasts/` | Yes | Generate a new forecast (async). Set `enableTuning: true` for Optuna hyperparameter optimization |
| `GET` | `/forecasts/` | Yes | List forecast history (paginated, filterable by product) |
| `GET` | `/forecasts/{id}` | Yes | Get full forecast details including all metrics and AI explanation |
| `GET` | `/forecasts/{id}/results` | Yes | Get forecast data points (predictions + confidence bounds + components) |
| `GET` | `/forecasts/{id}/components` | Yes | Get aggregated component breakdown (trend, weekly, yearly seasonality) |
| `GET` | `/forecasts/{id}/export/csv` | Yes | Download forecast results as CSV |
| `GET` | `/forecasts/{id}/export/chart` | Yes | Download forecast chart as PNG image |
| `GET` | `/forecasts/{id}/export/pdf` | Yes | Download full forecast report as PDF |
| `POST` | `/forecasts/{id}/share` | Yes | Generate a shareable link (optional: `expiresInHours`) |
| `DELETE` | `/forecasts/{id}/share` | Yes | Revoke a shareable link |

### Shared — `/api/v1/shared`

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `GET` | `/shared/forecasts/{token}` | **No** | View a shared forecast report (public) |

### Dashboard — `/api/v1/dashboard`

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `GET` | `/dashboard/` | Yes | Get quick stats (total products, total forecasts, average MAPE, last upload) and recent 5 forecasts |

### Profile — `/api/v1/profile`

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `GET` | `/profile/` | Yes | Get user profile and forecasting preferences |
| `PATCH` | `/profile/` | Yes | Update profile info and default forecast settings |
| `PUT` | `/profile/password` | Yes | Change password (requires current password) |
| `GET` | `/profile/holidays` | Yes | Get holiday calendar setting and list of supported country codes |
| `PUT` | `/profile/holidays` | Yes | Update holiday calendar country code |

### System — `/api/v1/health`

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `GET` | `/health` | No | API health check |

---

## Forecasting Pipeline

The pipeline runs as a **FastAPI `BackgroundTask`**, freeing the request thread immediately. The `POST /forecasts/` endpoint creates a `Forecast` record with `status=processing` and returns the ID. Results are written back to the database when the pipeline completes.

### Pipeline Steps

```
1. Load sales data from DB (SalesData rows → pandas DataFrame)
2. Preprocess
   ├── Remove duplicate dates
   ├── Rename columns to Prophet format (ds, y)
   ├── Fill missing date gaps (linear interpolation / zero-fill / forward-fill)
   ├── Cap/remove outliers using IQR method
   ├── Aggregate to weekly or monthly if requested
   └── (Optional) Merge weather regressors from Open-Meteo
3. Demand Profiling (ADI / CV² framework)
   ├── smooth      → low ADI, low CV²   → recommended: Prophet, Seasonal Naive
   ├── erratic     → low ADI, high CV²  → recommended: Prophet, Naive
   ├── intermittent→ high ADI, low CV²  → recommended: Croston SBA, Naive
   └── lumpy       → high ADI, high CV² → recommended: Croston SBA, Naive
4. Model Selection (rolling cross-validation)
   ├── Candidate models selected based on demand profile
   ├── Backtested over multiple rolling folds
   ├── Scored by WAPE (smooth/erratic) or MASE (intermittent/lumpy)
   └── Winner = lowest error metric
5. Final Model Training
   ├── Prophet: full re-train on all data with tuned parameters
   └── Baseline (Naive/Seasonal Naive/Croston SBA): applied directly
6. Accuracy Metrics Computation
   └── MAPE, WAPE, sMAPE, MASE, RMSE, MAE
7. AI Explanation Generation (Google Gemini)
   └── Contextual narrative explaining forecast, trends, and recommendations
8. Persist Results
   └── Update Forecast record: metrics, model params, status=completed
   └── Insert ForecastResult rows: one per day for the horizon
```

### Model Dictionary

| Model | Best For |
|---|---|
| `prophet` | Smooth and erratic demand with strong seasonality |
| `croston_sba` | Intermittent and lumpy demand (sparse non-zero sales) |
| `seasonal_naive` | Stable, highly seasonal patterns with limited data |
| `naive` | Flat baselines and all-zero series |

### MAPE Rating Thresholds

| Rating | MAPE Range |
|---|---|
| ✅ Excellent | < 15% |
| 🟡 Good | 15% – 30% |
| 🔴 Poor | > 30% |

---

## Environment Variables

Create a `.env` file in the project root (same level as `requirements.txt`). **Never commit real secrets.**

```env
# Database
DATABASE_URL=postgresql://<USER>:<PASSWORD>@localhost:5432/<DB_NAME>

# JWT Security
SECRET_KEY=your_long_random_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Google Gemini
GEMINI_API_KEY=your_gemini_api_key_here
```

### Full Settings Reference

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *(required)* | PostgreSQL connection string |
| `SECRET_KEY` | *(required)* | JWT signing secret |
| `ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token TTL in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token TTL in days |
| `GEMINI_API_KEY` | `""` | Google Gemini API key |
| `MAX_UPLOAD_SIZE_MB` | `10` | Maximum CSV upload size |
| `MAX_UPLOAD_ROWS` | `50000` | Maximum rows per CSV upload |
| `UPLOAD_SESSION_TTL_HOURS` | `24` | Time-to-live for pending CSV upload sessions |
| `APP_NAME` | `ShelfWise Inventory Forecasting API` | Application name shown in docs |
| `DEBUG` | `false` | Enable debug logging |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed CORS origins |

---

## Setup & Installation

### Prerequisites

- **Python 3.11+** (Python 3.14 is **not** supported due to Prophet/pandas build constraints)
- **PostgreSQL 18+** running locally or remotely
- A **Google Gemini API key** (free tier available at [ai.google.dev](https://ai.google.dev/))

> ⚠️ **Windows users:** Prophet requires C++ Build Tools to compile. Install them from [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) before running `pip install`.

### Step 1 — Clone the Repository

```bash
git clone <repository-url>
cd shelfwise-api
```

### Step 2 — Create a Virtual Environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

> **Note:** If pandas or Prophet fail to install on Windows due to missing build tools, install [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) first and then retry.

### Step 4 — Configure Environment Variables

```bash
cp .env.example .env   # or create .env manually
```

Edit `.env` with your database credentials, secret key, and Gemini API key. See [Environment Variables](#environment-variables) above.

### Step 5 — Set Up the Database

Create the PostgreSQL database:

```sql
CREATE DATABASE supplywise;
```

Then apply migrations with **Alembic** to create all tables:

```bash
# Generate the initial migration (first time only)
alembic revision --autogenerate -m "initial schema"

# Apply all migrations
alembic upgrade head
```

> **Note:** Alembic reads `DATABASE_URL` from your `.env` file automatically.

### Database Migrations with Alembic

After modifying any SQLAlchemy model, generate and apply a new migration:

```bash
# Generate a migration script from model changes
alembic revision --autogenerate -m "describe your change"

# Apply pending migrations
alembic upgrade head

# Rollback the last migration
alembic downgrade -1

# View migration history
alembic history
```

Alembic configuration:
- **`alembic.ini`** — main config file (at project root)
- **`alembic/env.py`** — imports all models and reads `DATABASE_URL` from app settings
- **`alembic/versions/`** — auto-generated migration scripts (commit these to version control)

---

## Running the Server

### Development

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The server will be available at:
- **API base:** `http://localhost:8000/api/v1`
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **Health check:** `http://localhost:8000/api/v1/health`

### Production

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## CSV Upload Format

The API expects a CSV file with the following columns:

| Column | Type | Required | Description |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | ✅ | Sale date |
| `product_id` | String | ✅ | SKU or product identifier |
| `product_name` | String | ✅ | Human-readable product name |
| `quantity_sold` | Integer / Float | ✅ | Units sold on that date |

**Example:**

```csv
date,product_id,product_name,quantity_sold
2025-01-01,SKU-001,Widget A,42
2025-01-02,SKU-001,Widget A,38
2025-01-03,SKU-001,Widget A,45
2025-01-01,SKU-002,Widget B,12
2025-01-02,SKU-002,Widget B,15
```

Download a ready-made template from: `GET /api/v1/upload/template`

### Upload Constraints

- Maximum file size: **10 MB** (configurable via `MAX_UPLOAD_SIZE_MB`)
- Maximum rows: **50,000** (configurable via `MAX_UPLOAD_ROWS`)
- Date format: **ISO 8601** (`YYYY-MM-DD`)
- Minimum data per product for forecasting: **~2 months** of history

---

## Response Format

Most JSON endpoints return a standardized envelope using the string field **`status`**: **`"success"`** or **`"error"`** (see `app/schemas/common.py` and `app/middleware/error_handler.py`). Field names in JSON are typically **camelCase** (Pydantic `CamelModel`).

### Success Response

```json
{
  "status": "success",
  "data": { },
  "message": "Optional message"
}
```

`message` is omitted when not provided.

### Paginated Response

```json
{
  "status": "success",
  "data": [ ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "totalItems": 150,
    "totalPages": 8
  }
}
```

### Error Response

Application errors raised as `AppException` are returned as:

```json
{
  "status": "error",
  "error": {
    "code": "NOT_FOUND",
    "message": "Product not found",
    "details": []
  }
}
```

`details` is a list (often empty); some validation errors populate it with field-level information.

### Health check (exception)

`GET /api/v1/health` does **not** use the same envelope. It returns a small monitoring payload:

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-03-22T12:00:00+00:00",
  "checks": {
    "database": "connected"
  }
}
```

Here `status` is **`healthy`** or **`degraded`**, not `success`.

### Common HTTP Status Codes

| Code | Meaning |
|---|---|
| `200` | OK |
| `201` | Created |
| `400` | Validation error / bad request |
| `401` | Unauthorized (missing or invalid token) |
| `403` | Forbidden |
| `404` | Resource not found |
| `409` | Conflict (e.g., duplicate email) |
| `422` | Unprocessable entity (Pydantic validation failure) |
| `429` | Rate limit exceeded |
| `500` | Internal server error |

---

## Request Flow (Client ↔ API)

1. **Transport** — The client (browser app, mobile app, or server) sends HTTP requests to the API base URL (for example `http://localhost:8000/api/v1/...`). For browser clients, the page origin must be allowed by **`CORS_ORIGINS`** (see `app/config.py`); `CORSMiddleware` adds the appropriate CORS headers on responses.

2. **Middleware stack** — In `app/main.py`, **`ActivityLoggingMiddleware`** wraps the app (outermost), then **`CORSMiddleware`**. The activity middleware records each request (path, method, duration, status) after the response is sent, without blocking the client.

3. **Routing** — FastAPI matches the path to a handler under **`/api/v1`** (`app/api/v1/router.py`).

4. **Dependencies** — Typical protected routes use:
   - **`get_db`** — Opens a SQLAlchemy session for the request and closes it afterward (`app/database.py`).
   - **`get_current_user`** — Reads **`Authorization: Bearer <access_token>`**, validates the JWT, loads the user (`app/dependencies.py`). Public routes (for example **`GET /api/v1/shared/forecasts/{token}`**) skip this.

5. **Handler → database / services** — The route runs business logic, queries or updates the database, and may queue **`BackgroundTasks`** (for example forecast generation in `app/api/v1/forecasts.py`).

6. **Response** — Handlers usually return dicts built with **`success_response`** / **`paginated_response`**. Uncaught **`AppException`** subclasses become JSON error bodies via **`app_exception_handler`**; any other exception becomes a generic **500** with `code: INTERNAL_ERROR`.

7. **Authentication flow** — **`POST /auth/register`**, **`/login`**, and **`/refresh`** return **`accessToken`** and **`refreshToken`**. Subsequent calls send **`Authorization: Bearer <accessToken>`**. The OpenAPI **`tokenUrl`** for the Bearer scheme is **`/api/v1/auth/login`** (Swagger “Authorize”); the live login body is still JSON as documented above.

---

## Testing

### Pytest (schema and helpers)

Install dependencies (includes **pytest** in `requirements.txt`), ensure the project root is on `PYTHONPATH`, then:

```bash
pytest tests/ -q
```

`tests/test_schema_envelope.py` checks **`success_response`** / **`paginated_response`** shapes without a running server or database.

### End-to-end script (live API + PostgreSQL)

With the API running locally and **`DATABASE_URL`** set in `.env`:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
# Windows
.venv\Scripts\python.exe tests/test_api.py

# macOS / Linux
source .venv/bin/activate && python tests/test_api.py
```

The script exercises register → upload → forecast → exports → share link → profile, and asserts HTTP status codes plus **`status: "success"`** / **`status: "error"`** envelopes where applicable.

---

## Security

### Authentication

- **Access tokens** (JWT, 30-minute TTL) are required for all protected endpoints.
- **Refresh tokens** (JWT, 7-day TTL) allow clients to obtain new access tokens without re-logging in.
- Tokens are signed with HS256 using `SECRET_KEY`.
- Pass the access token in the `Authorization` header:
  ```
  Authorization: Bearer <access_token>
  ```

### Password Policy

Passwords must meet all of the following:
- At least **8 characters**
- At least **1 uppercase** letter
- At least **1 lowercase** letter
- At least **1 digit**

### Rate Limiting

**SlowAPI** is wired on the app (`app.state.limiter` in `app/main.py`). Individual routes opt in with rate-limit decorators where configured; exceeding a limit returns HTTP **429 Too Many Requests** when enforced.

### CORS

CORS is configured via `CORS_ORIGINS` in settings. Default allows `http://localhost:3000` (the frontend dev server). Add production frontend domains to this list via the `.env` file:

```env
CORS_ORIGINS=["https://yourdomain.com", "https://app.yourdomain.com"]
```

### Data Isolation

All database queries are scoped to `user_id` from the JWT token — users can only access their own products, uploads, and forecasts.
