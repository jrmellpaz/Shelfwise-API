
# AI-Powered Inventory Forecasting System — Backend Reference

> **Source Documents:** Lapaz - Proposal.pdf, Lapaz - SRS.pdf
> **Author:** Jermel B. Lapaz
> **Adviser:** Ria Mae H. Borromeo
> **Institution:** University of the Philippines Cebu — BS Computer Science
> **SRS Version:** 2.0 (2026-01-05)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Database Design](#4-database-design)
5. [Functional Requirements (Backend)](#5-functional-requirements-backend)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [API Design & Endpoints](#7-api-design--endpoints)
8. [Backend Best Practices](#8-backend-best-practices)
9. [External Software Interfaces](#9-external-software-interfaces)
10. [Data Processing Pipeline](#10-data-processing-pipeline)
11. [Forecasting Engine](#11-forecasting-engine)
12. [AI Integration (Gemini API)](#12-ai-integration-gemini-api)
13. [Authentication & Security](#13-authentication--security)
    - [11.4 Passkey Authentication (WebAuthn) — Optional Enhancement](#114-passkey-authentication-webauthn--optional-enhancement)
14. [Export & Report Generation](#14-export--report-generation)
15. [System Models & Diagrams](#15-system-models--diagrams)
16. [Constraints, Assumptions & Dependencies](#16-constraints-assumptions--dependencies)
17. [Glossary](#17-glossary)
18. [Activity Logging](#18-activity-logging)

---

## 1. Project Overview

### 1.1 Problem Statement

Small and Medium-sized Enterprises (SMEs) face **ineffective inventory forecasting**, characterized by:

- **Overstocking** → freezes vital capital in unsold goods
- **Understocking** → missed sales and customer dissatisfaction

Existing solutions are either:

- **Enterprise ERPs** (SAP IBP, Oracle NetSuite) → too expensive and complex for SMEs
- **Manual methods** (Excel spreadsheets) → error-prone, no predictive power
- **Open-source ERPs** (Odoo, OpenBoxes) → require technical expertise to set up and maintain
- **IoT-integrated systems** → require hardware sensors, high cost

### 1.2 Project Objectives

1. Develop a **full-stack prototype** using Next.js (frontend), Python/FastAPI (backend), and PostgreSQL (database)
2. Users can **upload a CSV file**, **view a graphical forecast**, and **read AI-generated text**
3. Deliver an MVP by the end of the academic year
4. Develop/train/evaluate time-series forecasting models achieving **MAPE ≤ 20%**
5. Integrate the **Gemini API** to generate natural language explanations for each forecast

### 1.3 Target Users

**SME Owners/Managers** who:

- Have low to moderate technical expertise (no formal data science training)
- Possess strong business/inventory knowledge
- Interact with forecasting tools weekly to monthly
- Need explanations in plain English

### 1.4 Scope

**In scope:**

- **Multi-user support** with user registration and login
- Demand forecasting based on historical sales data only
- Primary input: structured CSV file (supports multi-product)
- Output: demand forecast (graphical) + AI-generated natural language explanation
- Complete data isolation between users (each user sees only their own data)

**Out of scope:**

- Real-time inventory tracking
- POS system integration or third-party software integration
- Supply chain logistics, supplier management, automatic purchase order generation
- Lead time calculations and reorder point recommendations
- Safety stock calculations
- Forecasting for products with zero historical sales data
- Data append or merge strategies
- Native mobile applications (iOS/Android)
- Custom ML model development from scratch

---

## 2. System Architecture

The system follows a **three-tier architecture**:

```
┌─────────────────────┐
│   Presentation      │  Next.js (React) — Frontend
│   Layer             │  PWA Support, Responsive Design
└────────┬────────────┘
         │ HTTP/HTTPS (REST API)
┌────────▼────────────┐
│   Business Logic    │  Python FastAPI — Backend
│   Layer             │  Prophet, Gemini API, Data Processing
└────────┬────────────┘
         │ psycopg2 / SQL
┌────────▼────────────┐
│   Data Layer        │  PostgreSQL 13+
└─────────────────────┘
```

### Data Flow

1. **User Interaction:** Users interact with Next.js frontend → upload CSV files, configure forecasts, view results
2. **Forecasting Pipeline:** Valid requests forwarded to Python FastAPI backend:
   - (a) CSV files are parsed, validated, and preprocessed
   - (b) Prophet models are configured based on data characteristics
   - (c) Forecasts are generated with confidence intervals
   - (d) Accuracy metrics are calculated
   - (e) Results are sent to the Gemini API for explanation generation
3. **Data Persistence:** All data (user info, historical sales, forecasts, AI explanations) stored in PostgreSQL with per-user data isolation
4. **Response Delivery:** Results returned to frontend for visualization
5. **Async Processing:** Long-running forecast generation handled via FastAPI BackgroundTasks to avoid blocking the API

---

## 3. Technology Stack

### 3.1 Backend (Application Layer)

| Technology  | Purpose                      | Rationale                                                                                                       |
| ----------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------- |
| **Python**  | Forecasting backend          | Dominant in data science/ML; ecosystem includes Prophet, pandas, numpy                                          |
| **FastAPI** | Python web framework for API | High performance, auto API docs, type validation, async support, suited for long-running forecasting operations |

### 3.2 Frontend (Application Layer)

| Technology  | Purpose                                                                |
| ----------- | ---------------------------------------------------------------------- |
| **Next.js** | React-based framework — SSR, built-in routing, API routes, PWA support |
| **React**   | Component-based UI library                                             |

### 3.3 Database Layer

| Technology         | Purpose                                                                                             |
| ------------------ | --------------------------------------------------------------------------------------------------- |
| **PostgreSQL 13+** | User accounts, historical sales data, forecast results, product metadata, AI-generated explanations |
| **psycopg2**       | Python PostgreSQL adapter for database connections                                                  |

### 3.4 Forecasting & AI Libraries

| Technology            | Version    | Purpose                                                                                                                                                    |
| --------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Facebook Prophet**  | `>= 1.1.0` | Core forecasting engine — handles business time series with strong seasonal patterns, interpretable decomposed components, robust to missing data/outliers |
| **Google Gemini API** | SDK        | Natural language generation for forecast explanations; accessed via the `google-genai` Python SDK                                                         |
| **google-genai**      | `>= 1.0.0` | Official Google Generative AI Python SDK — wraps Gemini API calls with structured output support                                                          |
| **Optuna**            | `>= 4.0.0` | Bayesian hyperparameter optimization for Prophet (changepoint/seasonality prior scales, seasonality mode)                                                  |
| **pandas**            | `>= 2.0.0` | Data manipulation and preprocessing                                                                                                                        |
| **numpy**             | `>= 1.24.0`| Numerical computations                                                                                                                                     |
| **requests**          | `>= 2.31.0`| HTTP client for Open-Meteo weather data API                                                                                                                |
| **python-dotenv**     | `>= 1.0.0` | Load environment variables from `.env` files                                                                                                               |
| **matplotlib**        | `>= 3.7.0` | Chart generation (Prophet dependency)                                                                                                                      |
| **pystan**            | `>= 3.0`   | Prophet dependency                                                                                                                                         |

### 3.5 Authentication Libraries

| Technology                     | Purpose                                                               |
| ------------------------------ | --------------------------------------------------------------------- |
| **python-jose** (or **PyJWT**) | JWT token creation and verification                                   |
| **passlib[bcrypt]**            | Password hashing with bcrypt                                          |
| **py_webauthn**                | _(Optional)_ WebAuthn/passkey registration and authentication (FIDO2) |

### 3.6 Infrastructure & Tooling

| Technology           | Purpose                                                                    |
| -------------------- | -------------------------------------------------------------------------- |
| **Alembic**          | Database migration tool for SQLAlchemy — version-controlled schema changes |
| **SQLAlchemy**       | Python ORM for database models and queries                                 |
| **Pydantic**         | Request/response validation and settings management (built into FastAPI)   |
| **slowapi**          | Rate limiting middleware for FastAPI                                       |
| **python-multipart** | Required for file upload handling in FastAPI                               |
| **uvicorn**          | ASGI server to run FastAPI in production                                   |

### 3.7 Deployment

| Item          | Detail                                         |
| ------------- | ---------------------------------------------- |
| **Platform**  | Railway                                        |
| **Protocol**  | HTTPS for all communications                   |
| **API Style** | RESTful API over HTTPS, versioned (`/api/v1/`) |

---

## 4. Database Design

### 4.1 Design Principles

- Primary keys use **UUID** for uniqueness and security
- Forecast results stored in a **separate table** (handles potentially thousands of data points per forecast)
- **Indexes** on foreign keys, date columns, and frequently queried fields
- **Cascade deletion** from users → products → sales data → forecasts (referential integrity)
- **All queries scoped by `user_id`** — ensures data isolation between users and leverages indexes for performance

### 4.1.1 Multi-User Data Scalability Safeguards

With multiple users, the `sales_data` table can grow to millions of rows. The following safeguards ensure the database remains performant:

| Strategy                                  | Detail                                                                                                   |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **Scope all queries by `user_id`**        | Every query includes `WHERE user_id = ?` so PostgreSQL uses the index instead of scanning the full table |
| **Composite indexes**                     | `(user_id, product_id)` and `(user_id, date)` ensure fast lookups even with millions of rows             |
| **Enforce upload limits**                 | Hard limit of **10MB per file** and **50,000 rows max** per upload                                       |
| **Paginate all list responses**           | Never return unbounded result sets from the API                                                          |
| **Store aggregated data for forecasting** | When preprocessing for Prophet, aggregate daily/weekly/monthly — this is what gets fed to the model      |

### 4.2 Entity-Relationship Overview

The database stores the following entities (based on the ER diagram in the Proposal/SRS):

#### `users` Table

| Column                     | Type         | Constraints                    | Notes                      |
| -------------------------- | ------------ | ------------------------------ | -------------------------- |
| `id`                       | UUID         | PK, DEFAULT uuid_generate_v4() |                            |
| `email`                    | VARCHAR      | UNIQUE, NOT NULL               | Login credential           |
| `password_hash`            | VARCHAR      | NOT NULL                       | bcrypt hashed with salt    |
| `business_name`            | VARCHAR      |                                | Editable in profile        |
| `contact_email`            | VARCHAR      |                                | Optional                   |
| `mobile_number`            | VARCHAR      |                                | Optional                   |
| `business_logo`            | VARCHAR/TEXT |                                | Optional, file path or URL |
| `default_forecast_period`  | INTEGER      | DEFAULT 3                      | Months (1–12)              |
| `default_confidence_level` | VARCHAR      | DEFAULT '95'                   | '80', '95', or 'both'      |
| `holiday_calendar`         | VARCHAR      | DEFAULT 'PH'                   | Country code for holidays  |
| `created_at`               | TIMESTAMP    | DEFAULT NOW()                  |                            |
| `updated_at`               | TIMESTAMP    |                                |                            |

#### `products` Table

| Column        | Type      | Constraints                      | Notes               |
| ------------- | --------- | -------------------------------- | ------------------- |
| `id`          | UUID      | PK                               |                     |
| `user_id`     | UUID      | FK → users(id) ON DELETE CASCADE |                     |
| `product_id`  | VARCHAR   | NOT NULL                         | From CSV data       |
| `name`        | VARCHAR   | NOT NULL                         | From CSV data       |
| `category`    | VARCHAR   |                                  | User-added metadata |
| `description` | TEXT      |                                  | User-added metadata |
| `notes`       | TEXT      |                                  | User-added metadata |
| `is_archived` | BOOLEAN   | DEFAULT FALSE                    | Soft archive        |
| `created_at`  | TIMESTAMP |                                  |                     |
| `updated_at`  | TIMESTAMP |                                  |                     |

#### `sales_data` Table

| Column          | Type      | Constraints                         | Notes                        |
| --------------- | --------- | ----------------------------------- | ---------------------------- |
| `id`            | UUID      | PK                                  |                              |
| `user_id`       | UUID      | FK → users(id) ON DELETE CASCADE    |                              |
| `product_id`    | UUID      | FK → products(id) ON DELETE CASCADE |                              |
| `date`          | DATE      | NOT NULL                            | Sales date                   |
| `quantity_sold` | NUMERIC   | NOT NULL, CHECK > 0                 | Must be positive numeric     |
| `upload_id`     | UUID      |                                     | Groups rows from same upload |
| `created_at`    | TIMESTAMP |                                     |                              |

#### `forecasts` Table

| Column             | Type      | Constraints                         | Notes                                                  |
| ------------------ | --------- | ----------------------------------- | ------------------------------------------------------ |
| `id`               | UUID      | PK                                  |                                                        |
| `user_id`          | UUID      | FK → users(id) ON DELETE CASCADE    |                                                        |
| `product_id`       | UUID      | FK → products(id) ON DELETE CASCADE |                                                        |
| `forecast_date`    | TIMESTAMP | NOT NULL                            | When forecast was generated                            |
| `forecast_horizon` | INTEGER   | NOT NULL                            | Days (default 90)                                      |
| `time_granularity` | VARCHAR   |                                     | 'daily', 'weekly', 'monthly'                           |
| `confidence_level` | VARCHAR   |                                     | '80', '95', 'both'                                     |
| `seasonality_mode` | VARCHAR   |                                     | 'auto', 'additive', 'multiplicative'                   |
| `selected_model`   | VARCHAR   |                                     | Model that won backtest: 'prophet', 'croston_sba', etc |
| `demand_profile`   | VARCHAR   |                                     | 'smooth', 'erratic', 'intermittent', 'lumpy'           |
| `mape`             | FLOAT     |                                     | Mean Absolute Percentage Error                         |
| `wape`             | FLOAT     |                                     | Weighted Absolute Percentage Error                     |
| `smape`            | FLOAT     |                                     | Symmetric Mean Absolute Percentage Error               |
| `mase`             | FLOAT     |                                     | Mean Absolute Scaled Error                             |
| `rmse`             | FLOAT     |                                     | Root Mean Squared Error                                |
| `mae`              | FLOAT     |                                     | Mean Absolute Error                                    |
| `data_start_date`  | DATE      |                                     | Start of historical data range used                    |
| `data_end_date`    | DATE      |                                     | End of historical data range used                      |
| `data_row_count`   | INTEGER   |                                     | Number of data rows used                               |
| `model_parameters` | JSONB     |                                     | Prophet configuration parameters used                  |
| `tuned_parameters` | JSONB     |                                     | Optuna-optimized hyperparameters (if tuning was used)  |
| `ai_explanation`   | TEXT      |                                     | Gemini-generated natural language explanation           |
| `created_at`       | TIMESTAMP |                                     |                                                        |

#### `forecast_results` Table (Separate for Performance)

| Column               | Type  | Constraints                          | Notes                        |
| -------------------- | ----- | ------------------------------------ | ---------------------------- |
| `id`                 | UUID  | PK                                   |                              |
| `forecast_id`        | UUID  | FK → forecasts(id) ON DELETE CASCADE |                              |
| `date`               | DATE  | NOT NULL                             | Future date                  |
| `predicted_value`    | FLOAT | NOT NULL                             | yhat                         |
| `lower_bound_80`     | FLOAT |                                      | yhat_lower (80%)             |
| `upper_bound_80`     | FLOAT |                                      | yhat_upper (80%)             |
| `lower_bound_95`     | FLOAT |                                      | yhat_lower (95%)             |
| `upper_bound_95`     | FLOAT |                                      | yhat_upper (95%)             |
| `trend`              | FLOAT |                                      | Trend component value        |
| `weekly_seasonality` | FLOAT |                                      | Weekly seasonality component |
| `yearly_seasonality` | FLOAT |                                      | Yearly seasonality component |

#### `passkeys` Table _(Optional — WebAuthn Enhancement)_

| Column          | Type      | Constraints                      | Notes                                                   |
| --------------- | --------- | -------------------------------- | ------------------------------------------------------- |
| `id`            | UUID      | PK, DEFAULT uuid_generate_v4()   |                                                         |
| `user_id`       | UUID      | FK → users(id) ON DELETE CASCADE | Owner of this passkey                                   |
| `credential_id` | BYTEA     | UNIQUE, NOT NULL                 | WebAuthn credential identifier (binary)                 |
| `public_key`    | BYTEA     | NOT NULL                         | COSE public key bytes                                   |
| `sign_count`    | INTEGER   | NOT NULL, DEFAULT 0              | Monotonic counter for clone detection                   |
| `device_name`   | VARCHAR   |                                  | User-assigned label (e.g., "MacBook Pro", "iPhone")     |
| `transports`    | JSONB     |                                  | Allowed transports: `["internal", "usb", "ble", "nfc"]` |
| `backed_up`     | BOOLEAN   | DEFAULT FALSE                    | Whether credential is backed up (multi-device)          |
| `last_used_at`  | TIMESTAMP |                                  | Last successful authentication                          |
| `created_at`    | TIMESTAMP | DEFAULT NOW()                    |                                                         |

### 4.3 Indexes (Recommended)

```sql
-- Single-column indexes
CREATE INDEX idx_products_user_id ON products(user_id);
CREATE INDEX idx_sales_data_user_id ON sales_data(user_id);
CREATE INDEX idx_sales_data_product_id ON sales_data(product_id);
CREATE INDEX idx_sales_data_date ON sales_data(date);
CREATE INDEX idx_forecasts_user_id ON forecasts(user_id);
CREATE INDEX idx_forecasts_product_id ON forecasts(product_id);
CREATE INDEX idx_forecasts_forecast_date ON forecasts(forecast_date);
CREATE INDEX idx_forecast_results_forecast_id ON forecast_results(forecast_id);
CREATE UNIQUE INDEX idx_users_email ON users(email);

-- Composite indexes for multi-user query performance
CREATE INDEX idx_sales_data_user_product ON sales_data(user_id, product_id);
CREATE INDEX idx_sales_data_user_date ON sales_data(user_id, date);
CREATE INDEX idx_forecasts_user_product ON forecasts(user_id, product_id);
```

---

## 5. Functional Requirements (Backend)

### FR-00: User Registration (New)

- Allow new users to **create an account** using email and password
- **Acceptance Criteria:**
  1. User provides email, password, and password confirmation
  2. System validates email format and uniqueness (no duplicate accounts)
  3. System enforces password strength (minimum 8 characters, at least one uppercase, one lowercase, one number)
  4. Password is hashed using **bcrypt with salt** before storage
  5. System creates the user record and returns a **JWT access token + refresh token**
  6. System returns error messages for invalid input (e.g., email already registered, weak password)
  7. Optional: user provides business name during signup (can also be set later in profile)
- **Priority:** Must Have

### FR-01: User Login

- Allow registered users to log in using **email and password**
- Grant access on valid credentials; display error message on invalid credentials
- Return a **JWT access token** (short-lived, 30 minutes) and a **refresh token** (long-lived, 7 days)
- **Priority:** Must Have

### FR-02: CSV File Upload

- Allow authenticated users to upload CSV files containing historical sales data
- Enforce a **hard file size limit of 10MB** and **maximum 50,000 rows** per upload
- Validate file encoding is **UTF-8**
- Validate file format and structure
- **Required CSV columns:** `date`, `product_id`, `product_name`, `quantity_sold`
- Supports **multi-product CSV files**
- Provide error messages for invalid files or files exceeding limits
- Uploaded data is associated with the **authenticated user's account** (user_id)
- **Priority:** Must Have

#### Data Replacement Strategy

The CSV file is the **single source of truth** for sales data. When a user uploads a new CSV, the system applies a **per-product replacement** strategy:

| Scenario                                            | Behavior                                                                                               |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| New CSV contains **same products** as existing data | Old `sales_data` rows for those products are **deleted and replaced** with the new rows                |
| New CSV contains **entirely new products**          | New product records are created; existing products' data is **untouched**                              |
| New CSV contains a **mix of old and new products**  | Old products' sales data is replaced; new products are added; products not in the CSV remain untouched |

**Key rules:**

- Only `sales_data` rows are replaced — **forecast history is always preserved** (forecasts and forecast_results are never deleted by an upload)
- Replacement is scoped to `(user_id, product_id)` — other users' data is never affected
- Products not present in the new CSV retain their existing sales data
- The `upload_id` on each `sales_data` row tracks which upload provided the current data

> **Rationale:** Since "data append or merge strategies" are out of scope (Section 1.4), the system treats each upload as a full refresh for the products it contains. Users maintain their sales records externally (e.g., in a spreadsheet) and export to CSV when they want updated forecasts. This avoids complex merge/conflict logic while keeping the database lean.

#### Pre-Upload Safety Check (Suspicious Replacement Detection)

To prevent accidental data loss (e.g., a CSV with one stray row of `SKU-001` replacing 365 existing rows), the upload process includes a **two-phase confirmation flow**:

**Phase 1 — Validate & Preview:** The system parses the CSV and compares it against existing data before committing anything:

```python
for product_id in new_csv_product_ids:
    old_count = db.count(sales_data WHERE product_id = ? AND user_id = ?)
    new_count = new_csv.count(product_id)

    if old_count > 0 and new_count < old_count * 0.5:  # Less than 50% of existing
        flag_as_suspicious(product_id, old_count, new_count)
```

**Phase 2 — User Confirmation:** The frontend displays an upload summary with warnings:

| Product | Current Records | New Records | Status                                      |
| ------- | --------------- | ----------- | ------------------------------------------- |
| SKU-007 | 0 (new)         | 400         | ✅ Add                                      |
| SKU-008 | 0 (new)         | 380         | ✅ Add                                      |
| SKU-001 | 365             | **1**       | ⚠ **Suspicious — significantly fewer rows** |

The user can then choose per product:

- **Include** — replace the data anyway (user confirms intentional)
- **Skip** — exclude this product from the upload (keep existing data)
- Or **Cancel** the entire upload

**API flow:**

1. `POST /api/v1/upload/` → stores CSV in a `csv_upload_sessions` row, returns column detection, suggested mappings, and **`uploadSessionId`**
2. `POST /api/v1/upload/validate` → body includes **`uploadSessionId`** and **`columnMap`**; returns quality preview and per-product summary (no data committed)
3. Frontend displays summary with suspicious replacement warnings
4. `POST /api/v1/upload/confirm` → body includes **`uploadSessionId`** and optional **`skipProductIds`**; user-confirmed data is committed

Pending sessions expire after **`UPLOAD_SESSION_TTL_HOURS`** (see server settings). Client integration notes: `references/FRONTEND_INTEGRATION.md`.

> **Note:** If no suspicious replacements are detected (all products have equal or more rows than before, or are entirely new), the confirmation step can be auto-approved by the frontend for a smoother experience.

### FR-03: Data Validation

- Validate uploaded data for completeness and accuracy:
  1. Check for **missing values** and flag incomplete records
  2. Ensure `quantity_sold` contains **numeric positive values**
  3. Identify and report **duplicate entries**
  4. Verify **minimum data length of 6 months** for reliable forecasting
  5. Provide option to **auto-correct common issues**
- **Priority:** Must Have

### FR-04: Data Preprocessing

- Preprocess validated data for Prophet forecasting:
  1. **Rename columns** to Prophet format: `ds` (date) and `y` (value/quantity_sold)
  2. Handle missing values through **interpolation or forward-fill**
  3. **Aggregate data** by specified time period (daily, weekly, or monthly)
  4. **Detect and handle outliers**
  5. Ensure **consistent time frequency** (daily intervals)
  6. **Fill missing dates** with appropriate values
- **Priority:** Must Have

### FR-05: Prophet Model Configuration

- Configure Prophet model based on data characteristics and user preferences:
  1. **Automatically detect seasonality** patterns (weekly, yearly)
  2. Allow user to specify **forecast horizon** (1–12 months)
  3. Configure appropriate **seasonality modes** (additive or multiplicative)
  4. Include **Philippine holidays by default**
  5. Allow users to **add custom events and holidays**
  6. Set appropriate **changepoint parameters** based on data volatility
- **Priority:** Must Have

### FR-06: Forecast Generation

- Generate demand forecasts using Facebook Prophet:
  1. **Initialize** the Prophet model with configured parameters
  2. **Train** the Prophet model on preprocessed historical data
  3. **Generate forecast** for user-specified period (1–12 months)
  4. Provide **confidence intervals** at 80% and 95%
  5. **Calculate accuracy metrics**: MAPE, RMSE, MAE
  6. **Extract** trend and seasonality components
  7. **Store** forecast results with metadata in the database
- **Priority:** Must Have

### FR-07: Forecast Visualization (Backend Data Support)

- Provide data for interactive forecast visualization:
  1. Main forecast plot data: historical data + predictions
  2. Confidence interval data (80% and 95%)
  3. Component breakdown data (trend, weekly seasonality, yearly seasonality)
  4. Support toggling between **daily, weekly, or monthly** aggregated views
  5. Exportable chart data as PNG images
- **Priority:** Must Have

### FR-08: AI-Generated Explanations

- Generate natural language explanations using Gemini API:
  1. **Extract key insights** from Prophet forecast:
     - Trend direction
     - Seasonality strength
     - Anomalies
  2. **Construct context prompt** including:
     - (a) Product name and category
     - (b) Historical average and recent performance
     - (c) Forecast summary (expected demand, growth rate)
     - (d) Trend description (increasing, decreasing, or stable)
     - (e) Seasonal patterns identified
     - (f) Confidence level and uncertainties
  3. **Send** structured prompt to Gemini API
  4. **Response must include** (in plain English):
     - (a) Summary of what the forecast predicts
     - (b) Why the pattern is expected (trend and seasonality analysis)
     - (c) Actionable recommendations for inventory planning (3–5 specific actions)
     - (d) Potential risks or uncertainties to monitor
  5. **Handle API failures** gracefully with fallback explanations or clear error messages
  6. **Store** the explanation with the forecast in the database
- **Priority:** Must Have

### FR-09: Forecast History

- Maintain a history of all generated forecasts:
  1. Provide list of past forecasts showing: forecast date, product names, forecast period, MAPE score, model parameters used
  2. Allow selecting and viewing any previous forecast with full details
  3. Store forecast metadata: date created, data range, Prophet parameters
  4. Support **search and filter** by product name, date, or accuracy
- **Priority:** Should Have

### FR-10: Export Reports

- Allow export of forecast reports:
  1. **PDF report** including:
     - (a) Cover page: product name, date generated, business name
     - (b) Executive summary of the forecast
     - (c) Main forecast chart (historical + prediction)
     - (d) Component plots (trend, seasonality)
     - (e) AI-generated explanation text
     - (f) Key metrics table (MAPE, RMSE, MAE, confidence intervals)
     - (g) Data summary (date range, sample size, model parameters)
  2. **CSV export** with fields: `date`, `predicted_value`, `lower_bound`, `upper_bound`
- **Priority:** Should Have

### FR-11: Dashboard Overview (Backend Data)

- Provide data for dashboard:
  1. Recent forecasts with thumbnail chart data
  2. Quick stats:
     - (a) Total products forecasted
     - (b) Total forecasts generated
     - (c) Average forecasting accuracy (average MAPE)
     - (d) Last upload date
  3. Data quality indicators for uploaded data
- **Priority:** Should Have

### FR-12: User Profile Management

- Allow profile management:
  1. Update business name and contact details
  2. Change password (requires current password verification)
  3. Update forecasting preferences: default forecast period, default confidence level
  4. Manage holiday calendar
  5. Confirm successful changes
- **Priority:** Should Have

### FR-13: Product Management

- Allow product information management:
  1. Return list of products from uploaded data
  2. List shows: product ID, name, category, last forecasted date, average MAPE
  3. Add product metadata: category, description, notes
  4. Filter products by category
  5. Archive products
- **Priority:** Should Have

---

## 6. Non-Functional Requirements

### NFR-01: Performance

| Metric                                       | Target                                           |
| -------------------------------------------- | ------------------------------------------------ |
| Page load time                               | < 3 seconds for all main pages                   |
| CSV upload processing                        | < 30 seconds for files up to 10MB (hard limit)   |
| Maximum rows per CSV upload                  | 50,000 rows                                      |
| Prophet model training + forecast generation | < 2 minutes for typical datasets (≤ 10,000 rows) |
| API response time (standard requests)        | < 500ms                                          |
| Database query execution (common queries)    | < 1 second                                       |
| Gemini API calls (explanation generation)    | < 10 seconds                                     |
| **Minimum server hardware**                  | **2 vCPUs, 4GB RAM**                             |

### NFR-02: Scalability

- Prophet models can be **cached** to avoid retraining with same parameters
- Forecasting jobs processed **asynchronously** using **FastAPI BackgroundTasks** to avoid blocking the API while Prophet trains
- All database queries scoped by `user_id` with composite indexes for multi-user performance
- All list endpoints return **paginated responses**

### NFR-03: Security

- All passwords must be **hashed using bcrypt with a salt**
- Authentication via **JWT tokens** (access token: 30 min, refresh token: 7 days)
- All protected endpoints require a valid JWT access token in the `Authorization: Bearer <token>` header
- API keys (Gemini, DB credentials) stored securely in **environment variables**
- HTTPS protocol for all communications
- **Data isolation:** Users can only access their own data — all queries filtered by authenticated user's ID

### NFR-04: Usability

- Maximum **3 clicks** to reach any major feature
- Consistent navigation across all pages
- Responsive design for mobile devices
- Dedicated **onboarding** for first-time users with full workflow

### NFR-05: Maintainability

- Code follows **PEP 8** (Python) and **ESLint** (JavaScript) style guides
- Version control using **Git** with meaningful commit messages

---

## 7. API Design & Endpoints

### 7.1 API Versioning

All API endpoints are prefixed with **`/api/v1/`** to support future versioning. If breaking changes are ever needed, a new version (`/api/v2/`) can be introduced without disrupting existing clients.

```
Base URL: https://<domain>/api/v1/
```

**Implementation in FastAPI:**

```python
from fastapi import APIRouter

# Create a versioned router
v1_router = APIRouter(prefix="/api/v1")

# Mount sub-routers
v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
v1_router.include_router(upload_router, prefix="/upload", tags=["Upload"])
v1_router.include_router(products_router, prefix="/products", tags=["Products"])
v1_router.include_router(forecasts_router, prefix="/forecasts", tags=["Forecasts"])
v1_router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
v1_router.include_router(profile_router, prefix="/profile", tags=["Profile"])

# Mount versioned router on main app
app.include_router(v1_router)
```

### 7.2 REST API Endpoints

All protected endpoints require a valid JWT access token in the `Authorization: Bearer <token>` header. Below are all endpoints under `/api/v1/`:

#### Authentication (Public — No Token Required)

| Method | Endpoint                | Description                                                           | FR    |
| ------ | ----------------------- | --------------------------------------------------------------------- | ----- |
| `POST` | `/api/v1/auth/register` | Create a new user account (email + password + optional business name) | FR-00 |
| `POST` | `/api/v1/auth/login`    | Authenticate user, return access token + refresh token                | FR-01 |
| `POST` | `/api/v1/auth/refresh`  | Exchange a valid refresh token for a new access token                 | FR-01 |

#### Authentication (Protected — Token Required)

| Method | Endpoint              | Description                          | FR    |
| ------ | --------------------- | ------------------------------------ | ----- |
| `POST` | `/api/v1/auth/logout` | Invalidate the current refresh token | FR-01 |
| `GET`  | `/api/v1/auth/me`     | Get current authenticated user info  | FR-01 |

#### Data Upload & Validation (Protected)

| Method | Endpoint                    | Description                                                                 | FR    |
| ------ | --------------------------- | --------------------------------------------------------------------------- | ----- |
| `POST` | `/api/v1/upload/`           | Upload CSV; returns **`uploadSessionId`** + column suggestions (max 10MB)   | FR-02 |
| `POST` | `/api/v1/upload/validate`   | Map columns + validate; requires **`uploadSessionId`** in body              | FR-02 |
| `POST` | `/api/v1/upload/confirm`    | Commit to DB; requires **`uploadSessionId`**, optional **`skipProductIds`** | FR-02 |
| `GET`  | `/api/v1/upload/template`   | Download sample CSV template                                                | FR-02 |

#### Products (Protected)

| Method  | Endpoint                        | Description                                            | FR    |
| ------- | ------------------------------- | ------------------------------------------------------ | ----- |
| `GET`   | `/api/v1/products`              | List all products (with filters, paginated)            | FR-13 |
| `GET`   | `/api/v1/products/{id}`         | Get product details                                    | FR-13 |
| `PATCH` | `/api/v1/products/{id}`         | Update product metadata (category, description, notes) | FR-13 |
| `PATCH` | `/api/v1/products/{id}/archive` | Archive/unarchive a product                            | FR-13 |

#### Forecasting (Protected)

| Method | Endpoint                            | Description                                                       | FR           |
| ------ | ----------------------------------- | ----------------------------------------------------------------- | ------------ |
| `POST` | `/api/v1/forecasts`                 | Generate a new forecast (async, returns forecast ID + status)     | FR-05, FR-06 |
| `GET`  | `/api/v1/forecasts`                 | List forecast history (search/filter/sort, paginated)             | FR-09        |
| `GET`  | `/api/v1/forecasts/{id}`            | Get full forecast details (results, explanation, metrics, status) | FR-09        |
| `GET`  | `/api/v1/forecasts/{id}/results`    | Get forecast result data points                                   | FR-07        |
| `GET`  | `/api/v1/forecasts/{id}/components` | Get component breakdown (trend, seasonality)                      | FR-07        |

#### Export (Protected)

| Method | Endpoint                              | Description                     | FR    |
| ------ | ------------------------------------- | ------------------------------- | ----- |
| `GET`  | `/api/v1/forecasts/{id}/export/pdf`   | Download forecast as PDF report | FR-10 |
| `GET`  | `/api/v1/forecasts/{id}/export/csv`   | Download forecast data as CSV   | FR-10 |
| `GET`  | `/api/v1/forecasts/{id}/export/chart` | Export chart as PNG image       | FR-07 |

#### Dashboard (Protected)

| Method | Endpoint            | Description                              | FR    |
| ------ | ------------------- | ---------------------------------------- | ----- |
| `GET`  | `/api/v1/dashboard` | Get dashboard stats and recent forecasts | FR-11 |

#### User Profile (Protected)

| Method  | Endpoint                   | Description                             | FR           |
| ------- | -------------------------- | --------------------------------------- | ------------ |
| `GET`   | `/api/v1/profile`          | Get user profile                        | FR-12        |
| `PATCH` | `/api/v1/profile`          | Update profile info/preferences         | FR-12        |
| `PUT`   | `/api/v1/profile/password` | Change password                         | FR-12        |
| `GET`   | `/api/v1/profile/holidays` | Get holiday calendar                    | FR-12        |
| `PUT`   | `/api/v1/profile/holidays` | Update holiday calendar / custom events | FR-05, FR-12 |

#### System (Public)

| Method | Endpoint         | Description                                               | FR  |
| ------ | ---------------- | --------------------------------------------------------- | --- |
| `GET`  | `/api/v1/health` | Health check endpoint (for Railway deployment monitoring) | —   |

### 7.3 Standardized API Response Format (Type-Safe)

All API responses are wrapped in type-safe Pydantic models using Python Generics. This ensures the response structure is validated at compile time and auto-documented in FastAPI's `/docs`.

All request and response payloads are **automatically converted** between snake_case (Python) and camelCase (JavaScript) via a shared base model. The frontend always sends and receives camelCase — the backend always works in snake_case internally.

#### 7.3.1 CamelCase ↔ snake_case Auto-Conversion (`app/schemas/base.py`)

```python
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class CamelModel(BaseModel):
    """Base model that converts snake_case ↔ camelCase automatically.

    - JSON output uses camelCase (e.g., totalItems, createdAt)
    - JSON input accepts camelCase (e.g., forecastPeriod, productId)
    - Python code uses snake_case internally (e.g., total_items, created_at)
    """
    model_config = ConfigDict(
        alias_generator=to_camel,    # snake_case → camelCase for JSON keys
        populate_by_name=True,       # Accept both snake_case and camelCase as input
    )
```

**Every Pydantic schema in the project extends `CamelModel` instead of `BaseModel`.** This means:

- `total_items` in Python → `"totalItems"` in JSON
- `created_at` in Python → `"createdAt"` in JSON
- `is_archived` in Python → `"isArchived"` in JSON
- Frontend can send `{ "forecastPeriod": 90 }` and Python receives it as `forecast_period`

#### 7.3.2 Core Response Schemas (`app/schemas/common.py`)

```python
from typing import Any, Generic, Optional, TypeVar
from app.schemas.base import CamelModel

T = TypeVar("T")

# --- Success Responses ---

class ApiResponse(CamelModel, Generic[T]):
    """Standard success response wrapper."""
    status: str = "success"
    data: T
    message: Optional[str] = None

class PaginationMeta(CamelModel):
    """Pagination metadata included in paginated responses."""
    page: int
    limit: int
    total_items: int       # → "totalItems" in JSON
    total_pages: int       # → "totalPages" in JSON

class PaginatedResponse(CamelModel, Generic[T]):
    """Success response with paginated data."""
    status: str = "success"
    data: list[T]
    pagination: PaginationMeta

# --- Error Responses ---

class ErrorDetail(CamelModel):
    """Structured error information."""
    code: str           # Machine-readable error code (e.g., "VALIDATION_ERROR")
    message: str        # Human-readable error message
    details: list[Any] = []  # Optional array of specific field errors or extra info

class ErrorResponse(CamelModel):
    """Standard error response wrapper."""
    status: str = "error"
    error: ErrorDetail
```

#### 7.3.2 Response Utility Functions (`app/schemas/common.py`)

```python
import math

def success_response(data: Any, message: Optional[str] = None) -> dict:
    """Create a standardized success response."""
    response = {"status": "success", "data": data}
    if message:
        response["message"] = message
    return response

def paginated_response(
    data: list, page: int, limit: int, total_items: int
) -> dict:
    """Create a standardized paginated response."""
    return {
        "status": "success",
        "data": data,
        "pagination": {
            "page": page,
            "limit": limit,
            "totalItems": total_items,
            "totalPages": math.ceil(total_items / limit) if limit > 0 else 0,
        },
    }
```

#### 7.3.4 Type-Safe Usage in Route Handlers

```python
# app/schemas/product.py
from app.schemas.base import CamelModel
from uuid import UUID
from datetime import datetime
from typing import Optional

class ProductResponse(CamelModel):
    id: UUID
    product_id: str         # → "productId" in JSON
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    is_archived: bool       # → "isArchived" in JSON
    created_at: datetime    # → "createdAt" in JSON

    class Config:
        from_attributes = True  # Enables ORM model → Pydantic conversion

# app/api/v1/products.py
from app.schemas.common import ApiResponse, PaginatedResponse, success_response, paginated_response
from app.schemas.product import ProductResponse

@router.get("/", response_model=PaginatedResponse[ProductResponse])
async def list_products(
    page: int = 1,
    limit: int = 20,
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    products, total = product_service.get_products(
        db, user_id=current_user.id, page=page, limit=limit, category=category
    )
    return paginated_response(
        data=[ProductResponse.from_orm(p) for p in products],
        page=page, limit=limit, total_items=total,
    )

@router.get("/{id}", response_model=ApiResponse[ProductResponse])
async def get_product(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = product_service.get_by_id(db, product_id=id, user_id=current_user.id)
    return success_response(data=ProductResponse.from_orm(product))
```

#### 7.3.5 Example JSON Responses

**Success — Single Resource (`GET /api/v1/products/{id}`):**

```json
{
  "status": "success",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "product_id": "SKU-001",
    "name": "Widget A",
    "category": "Electronics",
    "description": null,
    "is_archived": false,
    "created_at": "2026-02-14T12:00:00Z"
  }
}
```

**Success — Paginated List (`GET /api/v1/products?page=1&limit=20`):**

```json
{
  "status": "success",
  "data": [
    {
      "id": "...",
      "product_id": "SKU-001",
      "name": "Widget A",
      "category": "Electronics",
      "...": "..."
    },
    {
      "id": "...",
      "product_id": "SKU-002",
      "name": "Widget B",
      "category": "Electronics",
      "...": "..."
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "totalItems": 45,
    "totalPages": 3
  }
}
```

**Error — Validation (`POST /api/v1/upload`):**

```json
{
  "status": "error",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "CSV file is missing required columns",
    "details": ["Missing column: product_id", "Missing column: quantity_sold"]
  }
}
```

**Error — Authentication (`GET /api/v1/products` without token):**

```json
{
  "status": "error",
  "error": {
    "code": "AUTHENTICATION_ERROR",
    "message": "Missing or invalid access token",
    "details": []
  }
}
```

#### 7.3.6 Standard Error Codes

| Code                   | HTTP Status | Description                                  |
| ---------------------- | ----------- | -------------------------------------------- |
| `VALIDATION_ERROR`     | 422         | Invalid input data                           |
| `AUTHENTICATION_ERROR` | 401         | Missing or invalid JWT token                 |
| `AUTHORIZATION_ERROR`  | 403         | User doesn't have access to this resource    |
| `NOT_FOUND`            | 404         | Resource not found                           |
| `FILE_TOO_LARGE`       | 413         | Uploaded file exceeds 10MB limit             |
| `ROW_LIMIT_EXCEEDED`   | 422         | CSV exceeds 50,000 row limit                 |
| `INSUFFICIENT_DATA`    | 422         | Less than 6 months of historical data        |
| `FORECAST_FAILED`      | 500         | Prophet model training failed                |
| `AI_SERVICE_ERROR`     | 503         | Gemini API unavailable                       |
| `RATE_LIMIT_EXCEEDED`  | 429         | Too many requests                            |
| `INTERNAL_ERROR`       | 500         | Unexpected server error                      |
| `DUPLICATE_EMAIL`      | 409         | Email already registered                     |
| `WEAK_PASSWORD`        | 422         | Password does not meet strength requirements |
| `INVALID_CREDENTIALS`  | 401         | Wrong email or password                      |
| `TOKEN_EXPIRED`        | 401         | JWT token has expired                        |

---

## 8. Backend Best Practices

### 8.1 Modular Project Structure

The backend follows a **layered architecture** with clear separation of concerns. Each layer has a single responsibility:

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, middleware, router mounting
│   ├── config.py                # Pydantic Settings (environment config)
│   ├── database.py              # SQLAlchemy engine, session factory, Base
│   ├── dependencies.py          # Shared FastAPI dependencies (get_db, get_current_user)
│   │
│   ├── api/                     # ROUTE LAYER — HTTP handling only
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py        # v1 router that mounts all sub-routers
│   │       ├── auth.py          # /api/v1/auth/* endpoints
│   │       ├── upload.py        # /api/v1/upload/* endpoints
│   │       ├── products.py      # /api/v1/products/* endpoints
│   │       ├── forecasts.py     # /api/v1/forecasts/* endpoints
│   │       ├── dashboard.py     # /api/v1/dashboard/* endpoints
│   │       ├── profile.py       # /api/v1/profile/* endpoints
│   │       └── health.py        # /api/v1/health endpoint
│   │
│   ├── models/                  # DATA LAYER — SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── product.py
│   │   ├── sales_data.py
│   │   ├── forecast.py
│   │   └── forecast_result.py
│   │
│   ├── schemas/                 # SCHEMA LAYER — Pydantic request/response models
│   │   ├── __init__.py
│   │   ├── base.py              # CamelModel (auto snake_case ↔ camelCase conversion)
│   │   ├── common.py            # ApiResponse, PaginatedResponse, ErrorResponse, utilities
│   │   ├── auth.py              # RegisterRequest, LoginRequest, TokenResponse
│   │   ├── upload.py            # UploadResponse, ValidationResult
│   │   ├── product.py           # ProductResponse, ProductUpdate
│   │   ├── forecast.py          # ForecastRequest, ForecastResponse, ForecastStatus
│   │   ├── dashboard.py         # DashboardResponse, QuickStats
│   │   └── profile.py           # ProfileResponse, ProfileUpdate, PasswordChange
│   │
│   ├── services/                # SERVICE LAYER — Business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py      # Registration, login, token generation/validation
│   │   ├── upload_service.py    # CSV parsing, file size/row validation
│   │   ├── validation_service.py    # Data quality checks (FR-03)
│   │   ├── preprocessing_service.py # Column renaming, aggregation, outliers (FR-04)
│   │   ├── forecast_service.py  # Orchestrates forecast workflow
│   │   ├── prophet_service.py   # Prophet model config, training, prediction
│   │   ├── gemini_service.py    # Gemini API client, prompt construction
│   │   ├── export_service.py    # PDF and CSV report generation
│   │   └── dashboard_service.py # Dashboard stats aggregation
│   │
│   ├── core/                    # CORE UTILITIES
│   │   ├── __init__.py
│   │   ├── security.py          # JWT create/verify, password hash/verify
│   │   ├── exceptions.py        # Custom exception classes + error codes
│   │   └── logging.py           # Logging configuration
│   │
│   └── middleware/              # MIDDLEWARE
│       ├── __init__.py
│       └── error_handler.py     # Global exception handler
│
├── alembic/                     # Database migrations
│   ├── versions/                # Auto-generated migration files
│   └── env.py
├── tests/                       # Test files
│   ├── __init__.py
│   ├── conftest.py              # Shared test fixtures (test DB, test client)
│   ├── test_auth.py
│   ├── test_upload.py
│   ├── test_forecasts.py
│   └── test_products.py
├── alembic.ini
├── requirements.txt
├── .env.example
└── README.md
```

#### Layer Responsibilities

| Layer        | Directory       | Responsibility                                    | Rules                                                  |
| ------------ | --------------- | ------------------------------------------------- | ------------------------------------------------------ |
| **Routes**   | `app/api/v1/`   | Parse HTTP request, call service, return response | No business logic, no direct DB queries                |
| **Services** | `app/services/` | Business logic, orchestration, validation         | No HTTP-specific code, receives/returns Python objects |
| **Models**   | `app/models/`   | SQLAlchemy ORM table definitions                  | Pure data definitions, no logic                        |
| **Schemas**  | `app/schemas/`  | Pydantic request/response validation              | Input/output shapes, type enforcement                  |
| **Core**     | `app/core/`     | Cross-cutting utilities                           | Shared across all layers                               |

#### Data Flow Through Layers

```
HTTP Request
    → Route Handler (api/v1/products.py)
        → Validates input via Pydantic Schema (schemas/product.py)
        → Calls Service (services/product_service.py)
            → Queries DB via ORM Model (models/product.py)
            → Returns Python objects
        → Wraps result in Response Schema (schemas/common.py)
    → HTTP Response
```

### 8.2 Dependency Injection

FastAPI's `Depends()` system is used for shared dependencies. This keeps route handlers clean and testable.

#### Database Session (`app/database.py`)

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """Yields a DB session per request, auto-closes when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

#### Current User (`app/dependencies.py`)

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models.user import User
from app.core.exceptions import AppException

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Extracts and validates the current user from the JWT token.
    Used as a dependency in all protected routes."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise AppException(
                code="AUTHENTICATION_ERROR",
                message="Invalid token payload",
                status_code=401,
            )
    except JWTError:
        raise AppException(
            code="AUTHENTICATION_ERROR",
            message="Could not validate credentials",
            status_code=401,
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AppException(
            code="AUTHENTICATION_ERROR",
            message="User not found",
            status_code=401,
        )
    return user
```

#### Usage in Route Handlers

```python
# Every protected route simply adds these dependencies:
@router.get("/products")
async def list_products(
    current_user: User = Depends(get_current_user),  # Auth check
    db: Session = Depends(get_db),                     # DB session
):
    # current_user is guaranteed to be a valid, authenticated user
    # db is a fresh SQLAlchemy session scoped to this request
    products = db.query(Product).filter(Product.user_id == current_user.id).all()
    ...
```

### 8.3 Centralized Error Handling

All errors flow through a single global handler, ensuring every error response uses the standard format.

#### Custom Exceptions (`app/core/exceptions.py`)

```python
class AppException(Exception):
    """Base exception for all application errors."""
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: list | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []


# Specific exceptions for common scenarios

class AuthenticationException(AppException):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(code="AUTHENTICATION_ERROR", message=message, status_code=401)

class NotFoundException(AppException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(code="NOT_FOUND", message=f"{resource} not found", status_code=404)

class FileTooLargeException(AppException):
    def __init__(self, max_size_mb: int = 10):
        super().__init__(
            code="FILE_TOO_LARGE",
            message=f"File exceeds maximum size of {max_size_mb}MB",
            status_code=413,
        )

class RowLimitExceededException(AppException):
    def __init__(self, max_rows: int = 50000):
        super().__init__(
            code="ROW_LIMIT_EXCEEDED",
            message=f"CSV exceeds maximum of {max_rows:,} rows",
            status_code=422,
        )

class InsufficientDataException(AppException):
    def __init__(self):
        super().__init__(
            code="INSUFFICIENT_DATA",
            message="At least 6 months of historical data required",
            status_code=422,
        )

class ForecastFailedException(AppException):
    def __init__(self, reason: str = "Model training failed"):
        super().__init__(code="FORECAST_FAILED", message=reason, status_code=500)

class DuplicateEmailException(AppException):
    def __init__(self):
        super().__init__(
            code="DUPLICATE_EMAIL",
            message="An account with this email already exists",
            status_code=409,
        )

class RateLimitExceededException(AppException):
    def __init__(self):
        super().__init__(
            code="RATE_LIMIT_EXCEEDED",
            message="Too many requests. Please try again later.",
            status_code=429,
        )
```

#### Global Exception Handler (`app/middleware/error_handler.py`)

```python
from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.exceptions import AppException
import logging

logger = logging.getLogger(__name__)

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Catches all AppExceptions and returns a standardized error response."""
    logger.warning(
        f"AppException: {exc.code} - {exc.message}",
        extra={"path": request.url.path, "code": exc.code},
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        },
    )

async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catches any unhandled exceptions and returns a generic 500 error."""
    logger.error(
        f"Unhandled exception: {str(exc)}",
        extra={"path": request.url.path},
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": [],
            },
        },
    )
```

#### Registering Handlers (`app/main.py`)

```python
from fastapi import FastAPI
from app.core.exceptions import AppException
from app.middleware.error_handler import app_exception_handler, unhandled_exception_handler

app = FastAPI(title="Inventory Forecasting API", version="1.0.0")

# Register error handlers
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
```

#### Using Exceptions in Services (No Try/Catch in Routes)

```python
# app/services/upload_service.py
from app.core.exceptions import FileTooLargeException, RowLimitExceededException

def validate_upload(file: UploadFile, settings: Settings):
    # File size check
    file.file.seek(0, 2)  # Seek to end
    size_mb = file.file.tell() / (1024 * 1024)
    file.file.seek(0)      # Reset

    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise FileTooLargeException(max_size_mb=settings.MAX_UPLOAD_SIZE_MB)

    # Row count check
    df = pd.read_csv(file.file)
    if len(df) > settings.MAX_UPLOAD_ROWS:
        raise RowLimitExceededException(max_rows=settings.MAX_UPLOAD_ROWS)

    return df

# The route handler stays clean — no try/catch needed:
# app/api/v1/upload.py
@router.post("/")
async def upload_csv(file: UploadFile, ...):
    df = upload_service.validate_upload(file, settings)  # Raises on error
    result = upload_service.process_csv(df, user_id)
    return success_response(data=result, message="File uploaded successfully")
```

### 8.4 Rate Limiting

Rate limiting is implemented using **slowapi**, which wraps the [limits](https://limits.readthedocs.io/) library for FastAPI.

#### Setup (`app/main.py`)

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Create limiter — identifies users by IP address
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Register the rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

#### Per-Endpoint Rate Limits

```python
from slowapi import Limiter
from app.main import limiter

# Auth endpoints — prevent brute-force (by IP)
@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, credentials: LoginRequest, ...):
    ...

@router.post("/register")
@limiter.limit("3/minute")
async def register(request: Request, data: RegisterRequest, ...):
    ...

# Forecast generation — expensive operation (by IP, typically one user per session)
@router.post("/forecasts")
@limiter.limit("10/hour")
async def generate_forecast(request: Request, ...):
    ...

# File upload — prevent storage abuse
@router.post("/upload")
@limiter.limit("10/hour")
async def upload_csv(request: Request, ...):
    ...
```

#### Rate Limit Response

When a limit is exceeded, the API returns:

```json
{
  "status": "error",
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded: 5 per 1 minute",
    "details": []
  }
}
```

With HTTP headers:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 45
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1708000045
```

#### Rate Limit Summary

| Endpoint Group        | Limit      | Key | Reason                   |
| --------------------- | ---------- | --- | ------------------------ |
| `POST /auth/login`    | 5/minute   | IP  | Brute-force prevention   |
| `POST /auth/register` | 3/minute   | IP  | Spam account prevention  |
| `POST /upload`        | 10/hour    | IP  | Storage abuse prevention |
| `POST /forecasts`     | 10/hour    | IP  | CPU-intensive operation  |
| All other endpoints   | 100/minute | IP  | General abuse prevention |

### 8.5 Health Check Endpoint

#### Implementation (`app/api/v1/health.py`)

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
from app.database import get_db

router = APIRouter()

@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check for deployment monitoring.
    Tests database connectivity and returns system status."""
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "database": db_status,
        },
    }
```

#### Response Example

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-02-14T13:00:00+00:00",
  "checks": {
    "database": "connected"
  }
}
```

### 8.6 Application Entry Point (`app/main.py`)

This ties everything together — middleware, routers, error handlers, and CORS:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.core.exceptions import AppException
from app.middleware.error_handler import app_exception_handler, unhandled_exception_handler
from app.api.v1.router import v1_router

# --- App initialization ---
app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs",      # Swagger UI
    redoc_url="/redoc",     # ReDoc
)

# --- Rate limiter ---
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Error handlers ---
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# --- Routers ---
app.include_router(v1_router)
```

### 8.7 Configuration Management (Pydantic Settings)

```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Gemini API
    GEMINI_API_KEY: str

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = 10
    MAX_UPLOAD_ROWS: int = 50000

    # Application
    APP_NAME: str = "Inventory Forecasting API"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"

settings = Settings()
```

### 8.8 Database Migrations (Alembic)

Use **Alembic** for version-controlled schema changes instead of raw SQL:

```bash
# Initialize Alembic (one-time setup)
alembic init alembic

# Create a migration after changing models
alembic revision --autogenerate -m "add users table"

# Apply all pending migrations
alembic upgrade head

# Rollback last migration
alembic downgrade -1

# View migration history
alembic history
```

### 8.9 Structured Logging

```python
# app/core/logging.py
import logging
import sys

def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

# Usage in services:
logger = logging.getLogger(__name__)
logger.info("Forecast generated", extra={"user_id": user_id, "mape": mape})
logger.warning("Gemini API timeout", extra={"forecast_id": forecast_id})
logger.error("Prophet training failed", extra={"error": str(e)})
```

### 8.10 Environment File Template (`.env.example`)

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/inventory_forecast

# JWT
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Gemini API
GEMINI_API_KEY=your-gemini-api-key

# Application
DEBUG=true
CORS_ORIGINS=["http://localhost:3000"]
```

---

## 9. External Software Interfaces

**SI-01: Facebook Prophet Library**

- **Interface Type:** Python library (direct import)
- **Version:** `prophet >= 1.1.0`
- **Key Classes/Functions:**
  - `Prophet()` → Model initialization
  - `Prophet.fit(df)` → Model training
  - `Prophet.make_future_dataframe(periods)` → Create forecast horizon
  - `Prophet.predict(future)` → Generate predictions
  - `Prophet.plot(forecast)` → Visualization
  - `Prophet.plot_components(forecast)` → Component plots
- **Input Data Format:** pandas DataFrame with columns `ds` (datetime) and `y` (numeric)
- **Output:** DataFrame with predictions and confidence intervals
- **Configuration:**
  - Seasonality settings (yearly, weekly, daily)
  - Holiday effects
  - Changepoint prior scale
  - Seasonality mode (additive or multiplicative)
- **Error Handling:**
  - Insufficient data errors
  - Invalid parameter errors
  - Convergence warnings
- **Dependencies:** pystan >= 3.0, pandas >= 1.0.4, matplotlib >= 2.0.0

### 9.2 Gemini API

**SI-02: Gemini API**

- **Interface Type:** Python SDK (`google-genai`)
- **Purpose:** Generate natural language explanation of forecasts
- **Model:** `gemini-3.1-flash-lite-preview` (default, configurable)
- **Data Format:** Structured JSON output with `response_mime_type="application/json"`
- **Authentication:** API Key via environment variable (`GEMINI_API_KEY`)
- **Input:** Forecast summary, trend analysis, seasonality patterns, product context, model selection results, data quality warnings
- **Output:** Structured JSON with `summary`, `highlights`, `recommendations`, `risks`
- **Validation:** Schema validation + banned-word filtering + retry with corrective prompt
- **Error Handling:** Graceful fallback on API failures; up to 2 attempts with retry logic

### 9.2.5 Open-Meteo API

**SI-04: Open-Meteo Weather API**

- **Interface Type:** REST API over HTTPS (via `requests` library)
- **Purpose:** Provide temperature and precipitation data as Prophet regressors
- **Endpoint:** `https://api.open-meteo.com/v1/forecast` and `https://archive-api.open-meteo.com/v1/archive`
- **Authentication:** None (free, open API)
- **Input:** Latitude, longitude, date range
- **Output:** Daily temperature and precipitation values
- **Error Handling:** Graceful fallback — forecast proceeds without weather regressors if API fails

### 9.3 PostgreSQL Database

**SI-03: PostgreSQL Database**

- **Interface Type:** Database connection via `psycopg2`
- **Version:** PostgreSQL 13+
- **Authentication:** Username/password or connection string
- **Data Exchanged:**
  - User account and authentication data
  - Historical sales data
  - Forecast results and metadata
  - Product information
  - AI-generated explanations
  - Audit logs

---

## 10. Data Processing Pipeline

### 8.1 CSV Upload Flow

The upload follows a **two-phase process** to validate data before committing and protect against accidental data loss:

```
Phase 1 (Validate & Preview):
User uploads CSV → File Size Check (≤ 10MB) → Row Count Check (≤ 50K) → UTF-8 Encoding Check
→ Structure Validation → Data Validation → Compare against existing data per product
→ Return upload summary with warnings (suspicious replacements, validation issues)

Phase 2 (Confirm & Commit):
User reviews summary → Confirms or skips flagged products
→ Delete old sales_data for confirmed products → Insert new rows → Preprocessing → Done
```

**Data replacement rules:**

- For each `product_id` in the new CSV, existing `sales_data` rows for that product (scoped to the user) are **deleted and replaced** with the new rows
- Products **not** present in the new CSV are left untouched
- **Forecast history is never deleted** by an upload — only raw `sales_data` is replaced
- If a product's new row count is **less than 50%** of its existing row count, it is flagged as a **suspicious replacement** and requires user confirmation before committing

### 8.2 CSV Required Columns

| Column          | Type               | Description                       |
| --------------- | ------------------ | --------------------------------- |
| `date`          | Date/DateTime      | The date of the sales transaction |
| `product_id`    | String             | Unique product identifier         |
| `product_name`  | String             | Name of the product               |
| `quantity_sold` | Numeric (positive) | Number of units sold              |

### 8.3 Validation Rules (FR-03)

1. **Missing values:** Check for and flag incomplete records
2. **Quantity validation:** `quantity_sold` must be numeric and positive
3. **Duplicate detection:** Identify and report duplicate entries
4. **Minimum data length:** At least **6 months** of historical data for reliable forecasting
5. **Auto-correction option:** Provide option to auto-correct common issues

### 8.4 Preprocessing Steps (FR-04)

1. **Column Mapping & Renaming:**
   - Supports custom column names via `--col-date`, `--col-id`, `--col-name`, `--col-qty`
   - Maps to Prophet format: `date` → `ds`, `quantity_sold` → `y`
2. **Per-Product Filtering:** Extracts data for the target product, handles duplicate dates (sums quantities)
3. **Missing Date Fill (Gap-Fill):** Fills gaps in the date sequence using a configurable strategy:
   - `interpolate` (default) — linear interpolation between neighbors
   - `zero` — fill with 0 (appropriate for intermittent demand)
   - `ffill` — forward-fill from the last known value
4. **Outlier Detection & Handling:** IQR-based detection with configurable multiplier (default 1.5):
   - `cap` (default) — clip outliers to the IQR fence values
   - `remove` — replace outliers with NaN and interpolate
   - `none` — keep outliers as-is
   - Skipped automatically when the series has ≤ 10 non-zero data points
5. **Time Aggregation:** Aggregate by user-specified period:
   - Daily (default)
   - Weekly (sum within ISO week)
   - Monthly (sum within calendar month)
6. **Regressor Merging:** Merge optional weather data (temperature, precipitation) and/or user-provided external regressors (promo, payday, stockout flags) with forward-fill/back-fill for missing values

### 8.5 Data Quality Assessment

The system generates a **data quality scorecard** with an overall score (0–100) and rating. The score is computed from four weighted dimensions:

| Dimension       | Weight | Components                                                                                            |
| --------------- | ------ | ----------------------------------------------------------------------------------------------------- |
| **Completeness**| 35%    | Missing date %, missing quantity %, date gap ratio (gaps vs. expected consecutive dates)               |
| **Consistency** | 25%    | Coefficient of Variation score, outlier ratio (IQR-based), duplicate row ratio                        |
| **Freshness**   | 20%    | Days since last record — ≤7 days = very fresh (100), ≤30 = fresh (80), ≤90 = aging (50), >90 = stale (20) |
| **Volume**      | 20%    | Total data points — ≥365 rows = 100, ≥180 = 80, ≥50 = 50, <50 = 20                                     |

**Rating thresholds:**

| Score     | Rating      |
| --------- | ----------- |
| ≥ 80      | Excellent   |
| ≥ 60      | Good        |
| ≥ 40      | Fair        |
| < 40      | Poor        |

The scorecard output includes per-dimension scores, individual component values, and a list of human-readable warnings (e.g., "Over 30% of dates are missing", "Data has not been updated in 45 days").

---

## 11. Forecasting Engine

### 9.1 Prophet Configuration (FR-05)

| Parameter                      | Configuration Logic                                                             |
| ------------------------------ | ------------------------------------------------------------------------------- |
| **Seasonality detection**      | Automatically detect weekly, yearly patterns                                    |
| **Monthly Fourier seasonality**| Optional custom monthly seasonality (Fourier order tunable via Optuna)          |
| **Forecast horizon**           | User-specified in days (default: 90)                                            |
| **Seasonality mode**           | Auto-detect or user-specified: additive or multiplicative                       |
| **Holidays**                   | Optional country holidays; user can add custom events via holidays CSV          |
| **Changepoint prior scale**    | Set based on data volatility, or optimized by Optuna                            |
| **Seasonality prior scale**    | Controls flexibility of seasonal patterns, tunable by Optuna                    |

### 9.2 Forecast Generation Flow (FR-06)

```
Pipeline Steps:
 1. Load CSV — Read and validate file size / row limits
 2. Validate Structure — Check columns, clean nulls, fix types
 3. Data Quality Assessment — Score data health (0–100 scorecard)
 3.5. Weather Data (optional) — Fetch from Open-Meteo API
 4. Preprocess — Fill gaps, handle outliers, merge regressors
 5. Demand Profiling — Classify demand pattern (ADI/CV²)
 5.5. Hyperparameter Tuning (optional) — Optuna optimization
 5.6. Model Backtesting (optional) — Compare models on rolling windows
 6. Train Selected Model — Fit Prophet or best baseline model
 6.5. Trend Detection — Identify significant trend changes
 7. Cross-Validation — Calculate MAPE, WAPE, sMAPE, MASE, RMSE, MAE
 8. Format for Frontend — Structure JSON for charting
 9. Gemini Explanation — AI-generated business insights
10. Output — Store results in database
```

### 9.3 Accuracy Metrics

The pipeline calculates **6 accuracy metrics** via rolling-origin cross-validation:

| Metric    | Description                                                                                 | Target |
| --------- | ------------------------------------------------------------------------------------------- | ------ |
| **MAPE**  | Mean Absolute Percentage Error — avg absolute % diff between forecast and actual            | ≤ 20%  |
| **WAPE**  | Weighted Absolute Percentage Error — total error ÷ total demand; more stable than MAPE      | —      |
| **sMAPE** | Symmetric MAPE — handles small/zero values better than MAPE                                 | —      |
| **MASE**  | Mean Absolute Scaled Error — error relative to a naive forecast; below 1.0 beats naive      | < 1.0  |
| **RMSE**  | Root Mean Squared Error — penalizes large errors more heavily                               | —      |
| **MAE**   | Mean Absolute Error — avg absolute diff in same units as data                               | —      |

**MAPE Interpretation (for UI color coding):**

| MAPE      | Rating    | Color  |
| --------- | --------- | ------ |
| `< 15%`   | Excellent | Green  |
| `< 30%`   | Good      | Yellow |
| `≥ 30%`   | Poor      | Red    |

### 9.4 Demand Profiling

Before model selection, the pipeline classifies each product's demand pattern using two statistical measures:

- **ADI** (Average Demand Interval): average number of periods between non-zero sales
- **CV²** (squared Coefficient of Variation): variability of non-zero demand sizes

| Profile          | ADI     | CV²     | Characteristics                                   |
| ---------------- | ------- | ------- | ------------------------------------------------- |
| **Smooth**       | < 1.32  | < 0.49  | Frequent sales, stable demand sizes               |
| **Erratic**      | < 1.32  | ≥ 0.49  | Frequent sales, volatile demand sizes             |
| **Intermittent** | ≥ 1.32  | < 0.49  | Many zero-sale periods, stable non-zero demand    |
| **Lumpy**        | ≥ 1.32  | ≥ 0.49  | Many zero-sale periods, volatile non-zero demand  |

The demand profile drives candidate model selection and the choice of selection metric.

### 9.5 Model Selection & Backtesting

When model selection is enabled, the pipeline compares multiple forecasting strategies on the **same rolling-origin backtest windows**:

**Supported candidate models:**

| Model              | Best for                         | Description                                           |
| ------------------ | -------------------------------- | ----------------------------------------------------- |
| `prophet`          | Trend + seasonality patterns     | Full Prophet model with holidays and regressors       |
| `naive`            | Random walks, no clear patterns  | Predicts the last observed value                      |
| `seasonal_naive`   | Strong recurring patterns        | Repeats the most recent seasonal cycle                |
| `croston_sba`      | Intermittent/lumpy demand        | Designed for series with many zero-sale periods       |

**Automatic candidate selection** based on demand profile:

| Profile        | Default Candidates                         |
| -------------- | ------------------------------------------ |
| Smooth         | `prophet`, `seasonal_naive`, `naive`       |
| Erratic        | `prophet`, `naive`, `seasonal_naive`       |
| Intermittent   | `croston_sba`, `naive`, `prophet`          |
| Lumpy          | `croston_sba`, `naive`, `prophet`          |

**Selection metric defaults:**

- `auto` uses **MASE** for intermittent/lumpy/all-zero demand (stable when many periods are zero)
- `auto` uses **WAPE** for smooth/erratic demand (easy to interpret for denser series)
- Supported metrics: `mape`, `wape`, `smape`, `mase`, `rmse`, `mae`

**Backtest configuration:**

| Parameter          | Default              | Description                                            |
| ------------------ | -------------------- | ------------------------------------------------------ |
| `cv_initial_days`  | 60% of data range    | Initial training window before first test fold         |
| `cv_horizon_days`  | min(30, 20% of data) | Forecast horizon per fold                              |
| `cv_period_days`   | Same as horizon      | Step size (how far the window slides between folds)    |

**Deterministic tie-breaking:** When multiple models achieve the same best score, the pipeline uses a fixed priority order: Prophet > Croston SBA > Seasonal Naive > Naive > all others (alphabetical). This ensures reproducible results for identical input data.

The pipeline also reports **fold stability** (consistency of each model's scores across folds) and **winner margin** (how far ahead the winner is from the runner-up), so model choice is based on both average score and consistency.

### 9.6 Hyperparameter Tuning (Optuna)

When tuning is enabled, the pipeline uses **Optuna Bayesian optimization** to find optimal Prophet hyperparameters before the final training:

**Tunable parameters:**

| Parameter                  | Search Range       | Description                                     |
| -------------------------- | ------------------ | ----------------------------------------------- |
| `changepoint_prior_scale`  | 0.001 – 0.5       | Controls trend flexibility                      |
| `seasonality_prior_scale`  | 0.01 – 10.0       | Controls seasonality flexibility                |
| `seasonality_mode`         | additive / multiplicative | Whether seasonal effects are added or multiplied |
| `monthly_fourier_order`    | 0 – 5             | Custom monthly seasonality complexity (0 = off) |

**Configuration:**

- Default: **30 trials** (configurable via `tune_trials`)
- Each trial runs a Prophet cross-validation and evaluates MAPE
- Uses Tree-structured Parzen Estimator (TPE) sampler by default
- In testing: tuned parameters are cached to disk (`tuned_params_cache.json`) to avoid re-tuning identical data
- In production: tuned parameters are stored in the database (`tuned_parameters` JSONB column on the `forecasts` table) alongside the forecast results

### 9.7 Weather Regressors (Open-Meteo)

The pipeline can optionally merge weather data as Prophet regressors via the [Open-Meteo API](https://open-meteo.com/):

- **Historical weather:** temperature and precipitation for the full date range of the training data
- **16-day forecast weather:** real-time weather forecast for the first 16 days of the forecast horizon
- **Seasonal average fallback:** for forecast days beyond 16, uses day-of-year seasonal averages from the historical weather data

Requires latitude and longitude coordinates for the location. Weather values are forward-filled and back-filled to handle any API gaps.

### 9.8 External Regressors & Custom Holidays

**External regressors** are user-provided business signals that Prophet uses as additional predictors:

- Examples: promo flags, payday flags, stockout flags, campaign periods
- Provided via a separate CSV file with a date column and one or more binary/numeric regressor columns
- Supports product-specific regressors (optional product column)
- Missing regressor values are filled with 0
- For regressors to influence the forecast period, future dates must be included in the regressor CSV

**Custom holidays** allow users to define business events that affect sales patterns:

- Provided via a separate CSV with date and event name columns
- Optional columns: `product_id` (product-specific events), `lower_window` / `upper_window` (days before/after the event)
- Can be combined with Prophet's built-in country holidays

### 9.9 Trend Change Detection

After model training, the pipeline extracts **significant trend changepoints** from Prophet's internal mechanisms:

- Identifies points where the trend slope changes substantially
- For each changepoint, reports the date, direction (upward / downward shift), and magnitude
- Generates plain-English descriptions (e.g., "Significant upward trend shift detected around April 2025")
- Returned as a `trendChanges[]` array in the output for frontend visualization

### 9.10 Confidence Intervals

- **80% CI:** Narrower range, higher risk tolerance
- **95% CI:** Wider range, more conservative
- Both are computed and stored; user can choose to display one or both

### 9.11 Component Decomposition

Prophet decomposes the forecast into:

- **Trend:** Overall direction (increasing, decreasing, stable)
- **Weekly Seasonality:** Day-of-week patterns
- **Yearly Seasonality:** Month-of-year patterns
- **Holiday Effects:** Impact of holidays/events
- **Residual:** Unexplained variation

### 9.12 Caching & Async Processing

#### Async Forecast Generation with FastAPI BackgroundTasks

Prophet model training is the most CPU-intensive operation in the system (up to 2 minutes for large datasets). To prevent blocking the API for other users, forecast generation runs **asynchronously**:

```
1. User submits forecast request via POST /api/forecasts
2. API immediately returns a response with forecast ID + status: "processing"
3. FastAPI BackgroundTasks picks up the job and runs Prophet training in the background
4. Frontend polls GET /api/forecasts/{id} to check status
5. When complete, status changes to "completed" and results are available
6. If training fails, status changes to "failed" with an error message
```

**Forecast Status Values:**

- `processing` — Prophet model is training
- `generating_explanation` — Forecast done, waiting for Gemini API explanation
- `completed` — All results ready
- `failed` — An error occurred (with error message)

**Why FastAPI BackgroundTasks (not Celery):**

- Zero extra infrastructure — no Redis or message broker needed
- Runs in the same process — simpler deployment on Railway
- Sufficient for MVP scale (small number of concurrent users)
- Can be upgraded to Celery + Redis later if scaling demands it

---

## 12. AI Integration (Gemini API)

### 10.1 Prompt Construction (FR-08)

The system constructs a detailed, structured context prompt including:

| Context Item                              | Description                                                        |
| ----------------------------------------- | ------------------------------------------------------------------ |
| Product name and ID                       | Identifies what is being forecasted                                |
| Historical average and recent performance | Baseline context for comparison                                    |
| Forecast summary                          | Expected demand, growth rate, forecast horizon                     |
| Trend description                         | Increasing, decreasing, or stable                                  |
| Seasonal patterns identified              | Weekly/yearly patterns and their strength                          |
| Confidence level and uncertainties        | How reliable the forecast is                                       |
| Model selection results                   | Which model was selected and why (demand profile, backtest scores) |
| Data quality warnings                     | Any data health issues that may affect reliability                 |
| Weather regressors (if used)              | Temperature and precipitation context for disclaimer               |

### 10.2 Expected Output Structure

The AI-generated explanation is returned as **structured JSON** and must include:

| Field              | Type     | Description                                                                 |
| ------------------ | -------- | --------------------------------------------------------------------------- |
| `summary`          | string   | 2–3 sentence plain-English overview of what the forecast predicts           |
| `highlights`       | string[] | 3 key insights (plain English, no jargon)                                   |
| `recommendations`  | string[] | 3–5 specific, actionable inventory planning actions                         |
| `risks`            | string[] | 2–3 potential risks or uncertainties to monitor                             |

**Response validation:** The pipeline validates the Gemini response with:
- JSON parsing and schema validation (all required fields present, correct types)
- Banned-word filtering (e.g., rejects responses containing "MAPE", "Prophet", "yhat", "regressor" — no technical jargon)
- Retry logic: if validation fails on the first attempt, a corrective prompt is sent with the specific issues, and up to 2 total attempts are made

### 10.3 Error Handling

- API failures must be handled **gracefully**
- Provide **fallback explanations** or clear error messages when API is unavailable
- Handle: API downtime, rate limiting, quota exceeded, API deprecation

### 10.4 API Details

- **SDK:** `google-genai` Python SDK (not raw REST)
- **Model:** `gemini-3.1-flash-lite-preview` (default, configurable)
- **Auth:** API key stored in environment variable (`GEMINI_API_KEY`)
- **Output format:** Structured JSON via `response_mime_type="application/json"`
- **Performance Target:** < 10 seconds for explanation generation
- **Storage:** Explanation stored with the forecast in the database

---

## 13. Authentication & Security

### 11.1 Authentication — JWT (JSON Web Tokens)

The system uses **JWT-based authentication** with an access/refresh token pattern:

| Token             | Lifetime   | Purpose                                                               | Storage (Frontend)                              |
| ----------------- | ---------- | --------------------------------------------------------------------- | ----------------------------------------------- |
| **Access Token**  | 30 minutes | Sent with every API request in `Authorization: Bearer <token>` header | Memory (JavaScript variable) or httpOnly cookie |
| **Refresh Token** | 7 days     | Used to obtain a new access token when it expires                     | httpOnly cookie (secure, same-site)             |

#### JWT Auth Flow

```
1. User registers or logs in → backend returns access token + refresh token
2. Frontend stores access token and sends it with every API request
3. When access token expires (30 min), frontend sends refresh token to /api/auth/refresh
4. Backend validates refresh token → issues new access token
5. When refresh token expires (7 days), user must log in again
6. On logout, refresh token is invalidated server-side
```

#### JWT Token Payload (Access Token)

```json
{
  "sub": "<user_uuid>",
  "email": "user@example.com",
  "exp": 1708000000,
  "iat": 1708000000,
  "type": "access"
}
```

#### Registration Flow

1. User submits email, password, confirm password (and optional business name)
2. Backend validates: email format, email uniqueness, password strength (min 8 chars, uppercase, lowercase, number)
3. Password hashed with **bcrypt + salt**
4. User record created in `users` table
5. JWT access + refresh tokens returned

#### Password Requirements

- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one number

### 11.2 Security Requirements

| Requirement        | Detail                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------- |
| Password hashing   | bcrypt with salt (via `passlib[bcrypt]`)                                                          |
| Authentication     | JWT access tokens (30 min) + refresh tokens (7 days)                                              |
| Data isolation     | All queries filtered by authenticated user's `user_id` — users can never access other users' data |
| API keys           | Gemini API key, DB credentials stored in environment variables (never in code)                    |
| Communication      | HTTPS for all traffic                                                                             |
| Input validation   | Validate all form inputs and API inputs                                                           |
| File upload limits | 10MB max file size, 50K max rows                                                                  |
| Authorization      | All protected endpoints validate JWT before processing                                            |

### 11.3 Security Testing Plan

- **OWASP ZAP** scanning for common vulnerabilities:
  - SQL injection
  - XSS (Cross-Site Scripting)
  - Broken authentication
  - Sensitive data exposure
- Manual testing:
  - Registration and login flows
  - JWT token expiration and refresh flow
  - Input validation on all forms
  - Authorization on all API endpoints (ensure users can't access other users' data)
  - Token manipulation attempts

### 11.4 Passkey Authentication (WebAuthn) — Optional Enhancement

> **Priority: Nice to Have** — implement only if core features are complete and time permits. Passkeys supplement the existing email/password + JWT flow; they do **not** replace it.

#### What Are Passkeys?

Passkeys use the **WebAuthn / FIDO2** standard to let users authenticate with biometrics (fingerprint, face), a hardware security key, or a device PIN — eliminating passwords entirely for that login attempt. Major platforms (iOS 16+, Android 9+, Windows Hello, macOS Ventura+) support passkeys natively.

**Key benefits:**

- **Phishing-resistant** — credentials are bound to the origin (domain), so they can't be used on fake sites
- **No passwords to leak** — the private key never leaves the user's device
- **Faster login** — one biometric scan instead of typing a password

#### How Passkeys Coexist With Email/Password

```
┌─────────────────────────────────────────────┐
│              Login Screen                   │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │  Email: ________________________     │  │
│  │  Password: ____________________      │  │
│  │  [Log In]                            │  │
│  └───────────────────────────────────────┘  │
│                                             │
│              ── or ──                       │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │  🔐 Sign in with Passkey             │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

- Users **register** with email + password first (existing FR-00)
- Users can **optionally add a passkey** later via their profile (FR-12 extension)
- Both auth methods issue the **same JWT tokens** — downstream code is unchanged
- Users can have **multiple passkeys** (e.g., one per device)
- If a passkey is lost, users fall back to email + password

#### Library: `py_webauthn`

The Python [`py_webauthn`](https://github.com/duo-labs/py_webauthn) library handles all WebAuthn cryptography:

```bash
pip install py_webauthn
```

#### Passkey Registration Flow (Attestation)

Registration is a **two-step** process — the backend generates a challenge, the browser/device creates a credential, and the backend verifies it:

```
1. Authenticated user clicks "Add Passkey" in profile
2. Frontend calls  POST /api/v1/auth/passkeys/register/options
3. Backend generates registration options (challenge, user info, RP info)
4. Frontend passes options to navigator.credentials.create()
5. User performs biometric / PIN / security key interaction
6. Browser returns attestation response
7. Frontend sends attestation to  POST /api/v1/auth/passkeys/register/verify
8. Backend verifies and stores the credential in the `passkeys` table
```

**Step 1 — Generate Registration Options (`app/services/passkey_service.py`):**

```python
import webauthn
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
from app.config import settings
from app.models.passkey import Passkey

def generate_registration_options(user, existing_passkeys: list[Passkey]) -> dict:
    """Generate WebAuthn registration options for the authenticated user."""
    options = webauthn.generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,            # e.g., "yourdomain.com"
        rp_name=settings.WEBAUTHN_RP_NAME,        # e.g., "Inventory Forecasting"
        user_id=str(user.id).encode(),             # Unique user identifier
        user_name=user.email,
        user_display_name=user.business_name or user.email,
        # Prevent re-registering the same authenticator
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=pk.credential_id)
            for pk in existing_passkeys
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return options
```

**Step 2 — Verify Registration (`app/services/passkey_service.py`):**

```python
def verify_registration(credential_response: dict, expected_challenge: bytes) -> dict:
    """Verify the attestation response from the browser."""
    verification = webauthn.verify_registration_response(
        credential=credential_response,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.WEBAUTHN_RP_ID,
        expected_origin=settings.WEBAUTHN_ORIGIN,  # e.g., "https://yourdomain.com"
    )
    # Return the verified credential data to store
    return {
        "credential_id": verification.credential_id,        # bytes
        "public_key": verification.credential_public_key,    # bytes
        "sign_count": verification.sign_count,               # int
        "backed_up": verification.credential_backed_up,      # bool
    }
```

#### Passkey Login Flow (Assertion)

Login is also **two-step** — the backend sends a challenge, the device signs it with the stored private key:

```
1. User clicks "Sign in with Passkey" on the login screen
2. Frontend calls  POST /api/v1/auth/passkeys/login/options
3. Backend generates authentication options (challenge)
4. Frontend passes options to navigator.credentials.get()
5. User performs biometric / PIN / security key interaction
6. Browser returns assertion response
7. Frontend sends assertion to  POST /api/v1/auth/passkeys/login/verify
8. Backend verifies signature, issues JWT access + refresh tokens (same as password login)
```

**Step 1 — Generate Login Options:**

```python
def generate_authentication_options(passkeys: list[Passkey] | None = None) -> dict:
    """Generate WebAuthn authentication options.

    If passkeys are provided (user identified by email), only allow those.
    If None, allow any registered passkey (discoverable credential flow).
    """
    allow_credentials = None
    if passkeys:
        allow_credentials = [
            PublicKeyCredentialDescriptor(
                id=pk.credential_id,
                transports=pk.transports or [],
            )
            for pk in passkeys
        ]

    options = webauthn.generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options
```

**Step 2 — Verify Login:**

```python
def verify_authentication(credential_response: dict, expected_challenge: bytes,
                          stored_passkey: Passkey) -> int:
    """Verify the assertion response. Returns the new sign_count."""
    verification = webauthn.verify_authentication_response(
        credential=credential_response,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.WEBAUTHN_RP_ID,
        expected_origin=settings.WEBAUTHN_ORIGIN,
        credential_public_key=stored_passkey.public_key,
        credential_current_sign_count=stored_passkey.sign_count,
    )
    return verification.new_sign_count
```

#### API Endpoints

##### Passkey Registration (Protected — Token Required)

| Method | Endpoint                                 | Description                                        |
| ------ | ---------------------------------------- | -------------------------------------------------- |
| `POST` | `/api/v1/auth/passkeys/register/options` | Generate WebAuthn registration options (challenge) |
| `POST` | `/api/v1/auth/passkeys/register/verify`  | Verify attestation and store the new passkey       |

##### Passkey Login (Public — No Token Required)

| Method | Endpoint                              | Description                                          |
| ------ | ------------------------------------- | ---------------------------------------------------- |
| `POST` | `/api/v1/auth/passkeys/login/options` | Generate WebAuthn authentication options (challenge) |
| `POST` | `/api/v1/auth/passkeys/login/verify`  | Verify assertion, return JWT access + refresh tokens |

##### Passkey Management (Protected — Token Required)

| Method   | Endpoint                     | Description                        |
| -------- | ---------------------------- | ---------------------------------- |
| `GET`    | `/api/v1/auth/passkeys`      | List user's registered passkeys    |
| `PATCH`  | `/api/v1/auth/passkeys/{id}` | Update passkey label (device name) |
| `DELETE` | `/api/v1/auth/passkeys/{id}` | Remove a passkey                   |

#### Pydantic Schemas (`app/schemas/passkey.py`)

```python
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.schemas.base import CamelModel


# --- Registration ---

class PasskeyRegistrationOptions(CamelModel):
    """Response from /register/options — pass directly to navigator.credentials.create()."""
    options: dict  # Serialized PublicKeyCredentialCreationOptions

class PasskeyRegistrationVerify(CamelModel):
    """Request to /register/verify — the raw attestation from the browser."""
    credential: dict     # The full credential response from navigator.credentials.create()
    device_name: Optional[str] = None  # User-friendly label


# --- Authentication ---

class PasskeyLoginOptions(CamelModel):
    """Response from /login/options — pass directly to navigator.credentials.get()."""
    options: dict  # Serialized PublicKeyCredentialRequestOptions

class PasskeyLoginVerify(CamelModel):
    """Request to /login/verify — the raw assertion from the browser."""
    credential: dict  # The full credential response from navigator.credentials.get()


# --- Management ---

class PasskeyResponse(CamelModel):
    """Passkey info returned to the frontend (never expose keys)."""
    id: UUID
    device_name: Optional[str] = None
    backed_up: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class PasskeyUpdate(CamelModel):
    """Update a passkey's label."""
    device_name: str
```

#### Database Model (`app/models/passkey.py`)

```python
import uuid
from sqlalchemy import Column, ForeignKey, Integer, Boolean, String, LargeBinary, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Passkey(Base):
    __tablename__ = "passkeys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id = Column(LargeBinary, unique=True, nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    device_name = Column(String, nullable=True)
    transports = Column(JSONB, nullable=True)        # e.g., ["internal", "usb"]
    backed_up = Column(Boolean, default=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user = relationship("User", back_populates="passkeys")
```

> Add a `passkeys` relationship to the existing `User` model:
>
> ```python
> # In app/models/user.py, add:
> passkeys = relationship("Passkey", back_populates="user", cascade="all, delete-orphan")
> ```

#### Challenge Storage

Challenges are short-lived (typically 60 seconds). Store them in:

| Option                          | Detail                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------ |
| **Server-side session / cache** | Redis or an in-memory dict with TTL (preferred for production)                             |
| **Database**                    | A `webauthn_challenges` table with auto-expiry (simpler for MVP)                           |
| **Signed JWT**                  | Encode the challenge in a short-lived JWT returned to the frontend (stateless alternative) |

For MVP, a simple in-memory dict with TTL is sufficient:

```python
from datetime import datetime, timedelta, timezone

# Simple in-memory challenge store (replace with Redis in production)
_challenges: dict[str, tuple[bytes, datetime]] = {}

def store_challenge(user_id: str, challenge: bytes, ttl_seconds: int = 60):
    _challenges[user_id] = (challenge, datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))

def get_challenge(user_id: str) -> bytes | None:
    entry = _challenges.pop(user_id, None)
    if entry and entry[1] > datetime.now(timezone.utc):
        return entry[0]
    return None
```

#### Environment Variables

Add the following to `.env` and `app/config.py`:

```env
# WebAuthn / Passkeys (Optional)
WEBAUTHN_RP_ID=yourdomain.com
WEBAUTHN_RP_NAME=Inventory Forecasting
WEBAUTHN_ORIGIN=https://yourdomain.com
```

#### Security Considerations

| Concern                | Mitigation                                                                           |
| ---------------------- | ------------------------------------------------------------------------------------ |
| **Challenge replay**   | Challenges are single-use and expire after 60 seconds                                |
| **Credential cloning** | `sign_count` is verified on each login — if it doesn't increment, reject the attempt |
| **Origin validation**  | `expected_origin` and `expected_rp_id` are verified by `py_webauthn`                 |
| **User verification**  | Set to `PREFERRED` — biometric/PIN when available, graceful fallback otherwise       |
| **Lost passkey**       | Users can always fall back to email + password login                                 |
| **Multiple devices**   | Users can register multiple passkeys and manage them via the API                     |

---

## 14. Export & Report Generation

### 12.1 PDF Report (FR-10)

The downloadable PDF report includes:

1. **Cover page:** Product name, date generated, business name
2. **Executive summary** of the forecast
3. **Main forecast chart:** Historical data + prediction line
4. **Component plots:** Trend, seasonality breakdown
5. **AI-generated explanation text**
6. **Key metrics table:** MAPE, RMSE, MAE, confidence intervals
7. **Data summary:** Date range, sample size, model parameters

### 12.2 CSV Data Export (FR-10)

Exported CSV fields:

- `date`
- `predicted_value`
- `lower_bound`
- `upper_bound`

### 12.3 Chart Export (FR-07)

- Charts exportable as **PNG images**

---

## 15. System Models & Diagrams

### 13.1 Use Cases

| #   | Use Case                | Description                                                  |
| --- | ----------------------- | ------------------------------------------------------------ |
| 0   | Register                | New user creates an account                                  |
| 1   | Login                   | User authenticates to access the system                      |
| 2   | Upload Sales Data       | User uploads CSV with historical sales data                  |
| 3   | Generate Forecast       | User configures Prophet parameters and generates forecast    |
| 4   | View Forecast Results   | User views graphical forecast with LLM-generated explanation |
| 5   | View Component Analysis | User examines trend and seasonality components               |
| 6   | Export Forecast         | User downloads forecast as PDF or CSV                        |
| 7   | View Forecast History   | User accesses previously generated forecasts                 |
| 8   | Manage Products         | User manages product information and metadata                |
| 9   | Manage Profile          | User updates account info and preferences                    |

### 13.2 System Actors

| Actor             | Role                                       |
| ----------------- | ------------------------------------------ |
| SME Owner/Manager | Primary user                               |
| Gemini API        | Provides AI-generated explanations         |
| Prophet Library   | Generates forecasts and component analysis |

### 13.3 Use Case Relationships

- Upload Sales Data **extends** → Validate Data
- Generate Forecast **includes** → Train Prophet Model
- View Forecast Results **includes** → Generate AI Explanation

### 13.4 Traceability Matrix

| Requirement ID | Design Reference             | Test Case ID   |
| -------------- | ---------------------------- | -------------- |
| FR-00          | User Registration Module     | TC-AUTH-00     |
| FR-01          | User Login Module            | TC-AUTH-01     |
| FR-02          | Data Upload Module           | TC-DATA-01     |
| FR-03          | Data Validation Module       | TC-DATA-02     |
| FR-04          | Data Preprocessing Module    | TC-DATA-03     |
| FR-05          | Prophet Configuration Module | TC-FORECAST-01 |
| FR-06          | Forecasting Engine           | TC-FORECAST-02 |
| FR-07          | Visualization Module         | TC-VIS-01      |
| FR-08          | AI Integration Module        | TC-AI-01       |
| FR-09          | Forecast History Module      | TC-HIST-01     |
| FR-10          | Export Module                | TC-EXPORT-01   |
| NFR-01         | Performance Testing          | TC-PERF-01     |
| NFR-03         | Security Testing             | TC-SEC-01      |

---

## 16. Constraints, Assumptions & Dependencies

### 14.1 Technical Constraints

- Must use **Next.js, Python, PostgreSQL** with Prophet for forecasting
- AI explanation fully dependent on **Gemini API**
- Only accepts data via **structured CSV files**
- Can only forecast products with **existing historical sales data**
- Forecast horizon limited to **1–12 months**
- Optimized for typical SME datasets; extremely large datasets may degrade performance
- **Single-product forecasting** per operation (no batch processing in MVP)
- Prophet assumptions inherited:
  - Requires relatively regular historical patterns
  - Performs best with strong seasonal effects
  - May not handle sudden market disruptions well
  - Assumes piecewise linear trends

### 14.2 Business Constraints

- Development within a single academic semester (16 weeks, Feb–May 2026)
- Multi-user support with registration, but not a full SaaS platform (no billing, no admin panel, no tenant management)
- Limited budget restricts cloud resources and Gemini API calls

### 14.3 Regulatory Constraints

- Compliance with Gemini API terms of service
- Users must consent to data processing for forecasting purposes

### 14.4 Assumptions

1. Users upload reasonably clean historical sales data with minimal gaps
2. Sales patterns follow somewhat regular patterns
3. Users have stable internet connection
4. SMEs have at least **6–12 months** of historical sales data
5. Products have sufficient sales volume for forecasting
6. Users can operate basic computer/mobile applications
7. Users can follow CSV format instructions
8. Users can interpret business charts and graphs
9. Primary UI and AI explanations in **English only**
10. Forecasting needs are **1–12 months** ahead
11. Users upload new data and regenerate forecasts **monthly or quarterly**
12. No real-time forecasting needs
13. Business events and holidays significantly impact sales
14. Additive or multiplicative seasonality is appropriate

### 14.5 Critical Dependencies

| Dependency                      | Risk                                                 | Mitigation                                                 |
| ------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------- |
| **Facebook Prophet** (>= 1.1.0) | Core forecasting depends entirely on it              | Pin version, monitor for deprecation                       |
| **Gemini API**                  | Downtime, rate limiting, quota exceeded, deprecation | Monitor API status/quotas, implement fallback explanations |
| **PostgreSQL 13+**              | Database availability                                | Standard deployment practices                              |
| **Railway**                     | Deployment platform availability                     | Standard deployment practices                              |
| **python-jose / PyJWT**         | JWT token handling                                   | Pin version, well-maintained libraries                     |

---

## 17. Glossary

| Term                           | Definition                                                                                                                          |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| **Additive Seasonality**       | Seasonal fluctuations remain constant over time (e.g., +100 units every December)                                                   |
| **Multiplicative Seasonality** | Seasonal fluctuations grow proportionally with trend (e.g., +20% every December)                                                    |
| **Changepoint**                | A point in time where the trend changes direction or rate; Prophet auto-detects these                                               |
| **Confidence Interval**        | Range of values likely to contain the true forecast value at a specified confidence level (80% or 95%); wider = more uncertainty    |
| **MAPE**                       | Mean Absolute Percentage Error — average absolute % difference between forecast and actual. < 15% excellent, < 30% good, ≥ 30% poor |
| **WAPE**                       | Weighted Absolute Percentage Error — total absolute error ÷ total actual demand. More stable than MAPE for series with near-zero values |
| **sMAPE**                      | Symmetric Mean Absolute Percentage Error — handles small/zero values more robustly than MAPE                                            |
| **MASE**                       | Mean Absolute Scaled Error — error relative to a naive forecast. Below 1.0 means the model outperforms naive; preferred for intermittent demand |
| **ADI**                        | Average Demand Interval — average number of periods between non-zero demand events; used for demand profiling                           |
| **Demand Profile**             | Classification of a product's demand pattern (smooth, erratic, intermittent, lumpy) based on ADI and CV²                                |
| **MAE**                        | Mean Absolute Error — average absolute difference in same units as the data                                                         |
| **RMSE**                       | Root Mean Squared Error — penalizes large errors more heavily                                                                       |
| **Prophet Components**         | Decomposition: Trend (direction) + Seasonality (recurring patterns) + Holidays (event impact) + Residual (unexplained)              |
| **Trend**                      | Long-term data direction (upward, downward, flat), independent of seasonal fluctuations                                             |
| **Seasonality**                | Regular, predictable patterns repeating over fixed periods (daily, weekly, yearly)                                                  |
| **Overstocking**               | Excess inventory tying up capital                                                                                                   |
| **Understocking**              | Insufficient inventory leading to lost sales                                                                                        |
| **Time-Series**                | Data points collected at successive time intervals                                                                                  |
| **SME**                        | Small and Medium-sized Enterprise                                                                                                   |
| **JWT**                        | JSON Web Token — a compact, self-contained token for securely transmitting information between parties as a JSON object             |
| **Access Token**               | Short-lived JWT (30 min) sent with every API request to prove identity                                                              |
| **Refresh Token**              | Long-lived token (7 days) used to obtain a new access token without re-entering credentials                                         |
| **MVP**                        | Minimum Viable Product                                                                                                              |
| **PWA**                        | Progressive Web App                                                                                                                 |
| **SaaS**                       | Software as a Service                                                                                                               |

---

## Appendix: UI Pages & Frontend Context (For Backend API Design)

This section provides the frontend page structure so API endpoints return the correct data shapes.

### Registration Page (UI-00) — New

- Email, password, confirm password fields
- Optional: business name field
- "Sign Up" button → calls `POST /api/auth/register`
- Link to login page for existing users
- Backend returns: JWT access token + refresh token + user info

### Login Page (UI-01)

- Email + password fields
- "Log In" button → calls `POST /api/auth/login`
- Link to registration page for new users
- Backend returns: JWT access token + refresh token + user info

### Dashboard (UI-02)

- Sidebar nav: Dashboard, Upload Data, Generate Forecast, Forecast History, Profile
- Content: welcome message with business name, quick stats, recent forecasts, quick action buttons
- Backend must return: total forecasts, avg MAPE, active products, last activity, recent forecast list

### Upload Data Page (UI-03)

- Instructions with requirements checklist
- File upload dropzone (drag-and-drop or browse)
- Sample CSV download button
- After upload: data preview (first 10 rows), data summary (date range, row count, products), validation messages
- "Proceed to Forecast" button (enabled only after validation)

### Forecast Configuration Page (UI-04)

- Product selection dropdown (with search: product name + ID)
- Forecast period slider: 1–12 months (with number input)
- Time granularity: daily, weekly, monthly (radio buttons)
- Confidence level: 80%, 95%, or both (selector)
- Advanced options (collapsible):
  - Seasonality mode: auto, additive, multiplicative
  - Holiday calendar: Philippines default, option to change countries
- Historical trend mini-chart
- "Generate Forecast" button
- Estimated time indicator

### Forecast Results Page (UI-05)

- Header: product name + forecast date
- Main forecast chart: historical (solid) + forecast (dashed) + confidence intervals (shaded) + legend + hover tooltips
- Component tabs: Overall Trend, Weekly Seasonality
- AI Explanation panel: paragraphs, bullet points, key insights highlighted, recommendations (numbered), risk factors
- Metrics card: MAPE (prominent), RMSE, MAE, confidence level, data range, model parameters
- Action buttons: Export PDF, Export CSV, Generate New Forecast

### Forecast History Page (UI-06)

- Search by product name
- Date range picker
- Sort: newest, oldest, best accuracy
- Cards: product name, forecast date, thumbnail chart, MAPE badge (green < 15%, yellow 15–20%, red > 20%), "View Details" button
- Pagination

### Profile Page (UI-07)

- User info: email (read-only), business name, contact (email, mobile), business logo
- Password change: current + new + confirm
- Preferences: default forecast period, confidence level, holiday calendar
- Logout button

---

## 18. Activity Logging

With multi-user support, all significant user actions are logged for **accountability, debugging, and usage analytics**. Logging is implemented as a **non-blocking background task** — log writes happen _after_ the response is sent to the user, adding **zero latency** to API responses.

### 18.1 Design Principles

| Principle                    | Detail                                                                                                                                                        |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Non-blocking**             | All log writes use FastAPI `BackgroundTasks` — the response is returned first, then the log is persisted asynchronously                                       |
| **Zero user-facing latency** | Logging overhead (~1–5ms DB insert) occurs _after_ response delivery, so users experience no added delay                                                      |
| **Metadata only**            | Log the _what, who, when, and outcome_ — never the full CSV payload or Gemini response body. Store references (file size, row count, response length) instead |
| **Per-user scoping**         | Every log entry is tied to a `user_id`, enabling per-user audit trails                                                                                        |
| **Structured format**        | `details` stored as JSONB for flexible, queryable metadata without schema changes                                                                             |

### 18.2 Database Table: `activity_logs`

| Column        | Type         | Constraints                             | Notes                                        |
| ------------- | ------------ | --------------------------------------- | -------------------------------------------- |
| `id`          | UUID         | PK, DEFAULT uuid_generate_v4()          |                                              |
| `user_id`     | UUID         | FK → users(id) ON DELETE SET NULL, NULL | Nullable — preserves logs if user is deleted |
| `action`      | VARCHAR(100) | NOT NULL                                | Machine-readable action code (see 18.3)      |
| `details`     | JSONB        | DEFAULT '{}'                            | Flexible metadata — varies by action type    |
| `ip_address`  | VARCHAR(45)  |                                         | Client IP (supports IPv6)                    |
| `user_agent`  | VARCHAR(500) |                                         | Browser/client identifier                    |
| `duration_ms` | INTEGER      |                                         | Request duration in milliseconds             |
| `status_code` | INTEGER      |                                         | HTTP response status code                    |
| `created_at`  | TIMESTAMP    | DEFAULT NOW()                           | When the action occurred                     |

**Indexes:**

```sql
CREATE INDEX idx_activity_logs_user_id ON activity_logs(user_id);
CREATE INDEX idx_activity_logs_action ON activity_logs(action);
CREATE INDEX idx_activity_logs_created_at ON activity_logs(created_at);
CREATE INDEX idx_activity_logs_user_created ON activity_logs(user_id, created_at);
```

**SQLAlchemy Model (`app/models/activity_log.py`):**

```python
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.db.base import Base

class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    details = Column(JSONB, default=dict)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    duration_ms = Column(Integer)
    status_code = Column(Integer)
    created_at = Column(DateTime, server_default=func.now(), index=True)
```

### 18.3 Action Codes

| Action Code                | Trigger                          | Example Details (JSONB)                                                                 |
| -------------------------- | -------------------------------- | --------------------------------------------------------------------------------------- |
| `auth.register`            | User creates account             | `{"email": "user@example.com"}`                                                         |
| `auth.login`               | Successful login                 | `{}`                                                                                    |
| `auth.login_failed`        | Failed login attempt             | `{"email": "user@example.com", "reason": "invalid_password"}`                           |
| `auth.logout`              | User logs out                    | `{}`                                                                                    |
| `auth.token_refresh`       | Token refreshed                  | `{}`                                                                                    |
| `upload.csv`               | CSV file uploaded                | `{"filename": "sales.csv", "size_bytes": 52400, "row_count": 1200, "product_count": 5}` |
| `upload.validation_failed` | CSV validation failed            | `{"filename": "bad.csv", "errors": ["missing column: date"]}`                           |
| `forecast.started`         | Forecast generation begins       | `{"product_id": "P001", "horizon_months": 3, "granularity": "daily"}`                   |
| `forecast.completed`       | Forecast generation succeeds     | `{"product_id": "P001", "mape": 12.5, "duration_s": 8.2}`                               |
| `forecast.failed`          | Forecast generation fails        | `{"product_id": "P001", "error": "insufficient data"}`                                  |
| `gemini.called`            | Gemini API explanation requested | `{"model": "gemini-2.0-flash", "forecast_id": "..."}`                                   |
| `gemini.failed`            | Gemini API call fails            | `{"error": "rate_limit_exceeded"}`                                                      |
| `export.pdf`               | PDF report exported              | `{"forecast_id": "..."}`                                                                |
| `export.csv`               | CSV data exported                | `{"forecast_id": "..."}`                                                                |
| `profile.updated`          | Profile info changed             | `{"fields_changed": ["business_name", "default_forecast_period"]}`                      |
| `profile.password_changed` | Password changed                 | `{}`                                                                                    |

### 18.4 Implementation: Non-Blocking Background Task Logger

The core logging utility writes to the database as a **FastAPI BackgroundTask**, ensuring the log write never blocks the API response.

**Logger Service (`app/services/activity_logger.py`):**

```python
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.activity_log import ActivityLog
from app.db.session import async_session_factory


async def log_activity(
    user_id: UUID | None,
    action: str,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    duration_ms: int | None = None,
    status_code: int | None = None,
):
    """Write an activity log entry to the database.

    This function is designed to be called as a BackgroundTask,
    so it opens its own database session and commits independently.
    It never raises — errors are silently caught to avoid crashing
    the application over a failed log write.
    """
    try:
        async with async_session_factory() as session:
            entry = ActivityLog(
                user_id=user_id,
                action=action,
                details=details or {},
                ip_address=ip_address,
                user_agent=user_agent,
                duration_ms=duration_ms,
                status_code=status_code,
            )
            session.add(entry)
            await session.commit()
    except Exception:
        # Logging should never crash the application.
        # In production, send this to an error monitoring service (e.g., Sentry).
        pass
```

### 18.5 Middleware: Automatic Request-Level Logging

A middleware logs **every authenticated request** automatically — no code changes needed in individual endpoints. The log write is dispatched as a background task after the response is sent.

```python
# app/middleware/activity_logging.py
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import BackgroundTasks
from app.services.activity_logger import log_activity

# Paths that should not be logged (health checks, docs, etc.)
SKIP_PATHS = {"/api/v1/health", "/docs", "/openapi.json", "/redoc"}


class ActivityLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip non-API or unimportant paths
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        start_time = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # Extract user_id if authentication has set it on request.state
        user_id = getattr(request.state, "user_id", None)

        # Build the action code from method + path
        action = f"request.{request.method.lower()}"

        # Fire-and-forget: schedule log write as background task
        # This runs AFTER the response is already sent to the client
        background = BackgroundTasks()
        background.add_task(
            log_activity,
            user_id=user_id,
            action=action,
            details={"path": request.url.path, "query": str(request.query_params) or None},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:500],
            duration_ms=duration_ms,
            status_code=response.status_code,
        )
        response.background = background

        return response
```

**Registering the middleware (`app/main.py`):**

```python
from app.middleware.activity_logging import ActivityLoggingMiddleware

app = FastAPI(title="Inventory Forecasting API", version="1.0.0")
app.add_middleware(ActivityLoggingMiddleware)
```

### 18.6 Endpoint-Level Logging (Pipeline Steps)

For fine-grained pipeline logging (e.g., forecast started, forecast completed), use `BackgroundTasks` directly in the endpoint:

```python
# app/api/v1/forecasts.py
from fastapi import BackgroundTasks, Depends
from app.services.activity_logger import log_activity

@router.post("/", response_model=ApiResponse[ForecastStatusResponse])
async def create_forecast(
    payload: ForecastRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Start forecast generation
    forecast = await forecast_service.create(db, payload, current_user.id)

    # Log AFTER response — non-blocking
    background_tasks.add_task(
        log_activity,
        user_id=current_user.id,
        action="forecast.started",
        details={
            "product_id": str(payload.product_id),
            "horizon_months": payload.horizon_months,
            "granularity": payload.granularity,
        },
    )

    return success_response(data=forecast, message="Forecast generation started")
```

### 18.7 Performance Impact

| Component                                     | Time    | Impact on User                         |
| --------------------------------------------- | ------- | -------------------------------------- |
| **Background task DB insert**                 | ~1–5ms  | **None** — runs after response is sent |
| **Middleware overhead** (timing + state read) | ~0.01ms | Negligible                             |
| **Prophet forecast**                          | 2–30s   | This is the real bottleneck            |
| **Gemini API call**                           | 1–5s    | Second bottleneck                      |
| **Logging as % of total request time**        | ~0.001% | Effectively zero                       |

Since `log_activity` opens its own database session and the write is dispatched via `response.background`, the **response is already delivered to the client** before the log hits the database. Even under heavy multi-user load, connection pooling ensures log writes share a small pool of DB connections (e.g., 10–20) without contention.

### 18.8 Log Retention & Cleanup

To prevent unbounded table growth:

| Strategy                    | Implementation                                                                                     |
| --------------------------- | -------------------------------------------------------------------------------------------------- |
| **Retention period**        | Keep logs for 90 days by default                                                                   |
| **Scheduled cleanup**       | Run a daily/weekly cron job or FastAPI startup task to delete old logs                             |
| **Partitioning (optional)** | For high-volume deployments, partition `activity_logs` by `created_at` month for fast bulk deletes |

**Cleanup query:**

```sql
DELETE FROM activity_logs WHERE created_at < NOW() - INTERVAL '90 days';
```

**FastAPI scheduled cleanup (using `asyncio` on startup):**

```python
import asyncio
from datetime import timedelta
from sqlalchemy import delete, text
from app.models.activity_log import ActivityLog
from app.db.session import async_session_factory

async def cleanup_old_logs(retention_days: int = 90):
    """Periodically delete logs older than the retention period."""
    while True:
        try:
            async with async_session_factory() as session:
                stmt = delete(ActivityLog).where(
                    ActivityLog.created_at < text(f"NOW() - INTERVAL '{retention_days} days'")
                )
                result = await session.execute(stmt)
                await session.commit()
        except Exception:
            pass
        # Run once per day
        await asyncio.sleep(86400)

@app.on_event("startup")
async def start_log_cleanup():
    asyncio.create_task(cleanup_old_logs())
```
