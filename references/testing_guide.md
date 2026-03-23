# Complete Backend Testing Guide: ShelfWise API

This guide provides the exact `curl` commands needed to test the core flow of the application: Authenticaton > 3-Step CSV Upload (with column mapping) > Forecasting.

**Prerequisites:** 
- The backend server should be running locally on `http://127.0.0.1:8000`.
- Have a terminal open. If on Windows Command Prompt, replace single quotes (`'`) with double quotes (`"`) around JSON strings.

---

### Step 1: Health Check (Verify DB Connection)

Ensure the server is running and the database is connected.

**Command:**
```bash
curl -s http://127.0.0.1:8000/api/v1/health
```
**Expected Result:** A JSON response containing `"status": "healthy"` and `"database": "connected"`.

---

### Step 2: Register a New User

Create a fresh test user account.

**Command:**
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"testuser@shelfwise.com", "password":"TestPass123", "passwordConfirm":"TestPass123", "businessName":"My Store"}'
```
**Expected Result:** A success response containing an `"accessToken"`.

*(If you get a `DUPLICATE_EMAIL` error, use the login command instead or change the email.)*

**Set your Token Variable:**
Copy the `accessToken` from the response (without quotes) and save it in your terminal variable to make subsequent requests easier:
```bash
# macOS/Linux (Git Bash)
export TOKEN="your_access_token_here"

# Windows Command Prompt
set TOKEN="your_access_token_here"

# Windows PowerShell
$TOKEN="your_access_token_here"
```

---

### Step 3: Phase 1 Upload (Detect Columns & Auto-Suggest)

Upload your [fast.csv](file:///c:/Users/user/Documents/shelfwise-api/references/fast.csv) dataset. The backend will parse the headers and suggest column mappings without committing anything to the DB.

**Command (macOS/Linux/Git Bash):**
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/upload/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@references/fast.csv"
```
**Expected Result:** A response showing `"uploadSessionId"`, `"columns": ["term", "sale_date", "product_id", "total_items_sold", "total_revenue"]`, and `"suggestedMapping"` showing how the backend matched `total_items_sold` to `quantity_sold`, etc. Save `uploadSessionId` for the next two steps (example below uses `$SESSION`).

---

### Step 4: Phase 2 Upload (Validate Data Quality)

Send **`uploadSessionId`** plus the column mapping. The server loads the CSV from the persisted session, applies renames, checks for anomalies, and returns a data health scorecard.

**Command:**
```bash
# Set SESSION from step 3, e.g. SESSION=$(curl -s ... | jq -r '.data.uploadSessionId')
curl -s -X POST http://127.0.0.1:8000/api/v1/upload/validate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"uploadSessionId\": \"$SESSION\", \"columnMap\": {\"date\": \"sale_date\", \"product_id\": \"product_id\", \"quantity_sold\": \"total_items_sold\"}}"
```
**Expected Result:** A response payload including an overall `dataHealth` score (0-100), quality/validation warnings, and a per-product summary of new rows detected. No data is saved to the DB yet.

---

### Step 5: Phase 3 Upload (Confirm & Commit)

Confirm the upload to write the validated data to the PostgreSQL database. The body must include the same **`uploadSessionId`**.

**Command:**
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/upload/confirm \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"uploadSessionId\": \"$SESSION\", \"skipProductIds\": []}"
```
**Expected Result:** A response confirming data was committed, e.g., `"message": "Upload committed — XYZ rows inserted"`.

---

### Step 6: Verify Products Created

Make sure the products were auto-extracted from the CSV and created.

**Command:**
```bash
curl -s http://127.0.0.1:8000/api/v1/products/ \
  -H "Authorization: Bearer $TOKEN"
```
**Expected Result:** A paginated list of products from your dataset. Find one of the `"id"` values (e.g. `ca6143c1-...`) for the next step.

---

### Step 7: Generate a Forecast

Trigger the Prophet machine learning pipeline for a specific product. Replace `<PRODUCT_UUID>` with an ID from the previous step.

**Command:**
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/forecasts/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"productId": "<PRODUCT_UUID>", "horizonDays": 30, "timeGranularity": "daily", "confidenceLevel": "95"}'
```
**Expected Result:** A response stating `"status": "pending"` and returning a new Forecast ID. 

---

### Step 8: Poll for Forecast Completion

Use the Forecast ID from Step 7 to check the status. Replace `<FORECAST_UUID>`.

**Command:**
```bash
curl -s http://127.0.0.1:8000/api/v1/forecasts/<FORECAST_UUID> \
  -H "Authorization: Bearer $TOKEN"
```
**Expected Result:** Keep calling this until `"status"` changes from `"pending"` or `"processing"` to `"completed"`. The response will include metrics like MAPE/RMSE, the AI explanation from Gemini, and seasonality classifications.

---

### Step 9: Get Forecast Results

Retrieve the actual graph data points (predicted values, lower/upper confidence bounds).

**Command:**
```bash
curl -s http://127.0.0.1:8000/api/v1/forecasts/<FORECAST_UUID>/results \
  -H "Authorization: Bearer $TOKEN"
```
**Expected Result:** An array of dates mapped to `predictedValue`, `lowerBound95`, and `upperBound95` used to draw the charts on the frontend.
