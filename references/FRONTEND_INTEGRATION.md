# Frontend Integration Guide — Shelfwise API

Reference for building the Shelfwise SPA against the backend at `/api/v1`.

**Stack assumptions**: TanStack Start · TanStack Router · TailwindCSS · SilkHQ (manual modal/popup wiring).

---

## 1. Response Envelope

Every response from the API follows one of two shapes. The frontend should always check `status` first.

### Success (single resource)

```json
{
  "status": "success",
  "data": { ... },
  "message": "Optional human-readable string"
}
```

### Success (paginated list)

```json
{
  "status": "success",
  "data": [ ... ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "totalItems": 150,
    "totalPages": 8
  }
}
```

### Error

```json
{
  "status": "error",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable explanation",
    "details": []
  }
}
```

All keys are **camelCase**. Backend schemas auto-convert `snake_case` ↔ `camelCase`, so send request bodies in camelCase too.

### Error Codes Reference

| Code | HTTP | Typical Trigger |
|------|------|-----------------|
| `AUTHENTICATION_ERROR` | 401 | Missing/invalid bearer token |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password on login |
| `TOKEN_EXPIRED` | 401 | JWT access token expired |
| `AUTHORIZATION_ERROR` | 403 | Accessing another user's resource |
| `NOT_FOUND` | 404 | Resource doesn't exist or doesn't belong to user |
| `DUPLICATE_EMAIL` | 409 | Email already registered |
| `SESSION_EXPIRED` | 410 | Upload session has expired (older than `UPLOAD_SESSION_TTL_HOURS`) |
| `FILE_TOO_LARGE` | 413 | CSV > `MAX_UPLOAD_SIZE_MB` (default 10 MB) |
| `VALIDATION_ERROR` | 422 | Generic validation failure (check `details[]`) |
| `ROW_LIMIT_EXCEEDED` | 422 | CSV > `MAX_UPLOAD_ROWS` (default 50 000) |
| `WEAK_PASSWORD` | 422 | Password doesn't meet strength rules |
| `INSUFFICIENT_DATA` | 422 | < 6 months of historical data for forecasting |
| `FORECAST_FAILED` | 500 | Model training failed |
| `AI_SERVICE_ERROR` | 503 | Gemini API unavailable |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unhandled server exception |

---

## 2. Auth-Aware HTTP Client

Create a shared API client (e.g. `src/lib/api.ts`) that wraps `fetch`:

1. Attach `Authorization: Bearer <accessToken>` to every protected request.
2. On **401**, call `POST /api/v1/auth/refresh` with the stored refresh token; update the access token; retry the request **once**.
3. If refresh fails, clear all auth state and navigate to the login view.

### Recommended – TanStack Start Server Functions

Since TanStack Start supports **server functions** (type-safe RPCs), you can create a server function that proxies requests to the backend. This keeps tokens in server-only context and prevents leaking credentials to the client bundle. However, since this is an SPA that calls an external API, a **client-side fetch wrapper** is simpler and perfectly fine for this use case.

### Token Storage

- **Access token**: keep in memory (React state / context). Short-lived (30 min default).
- **Refresh token**: keep in `localStorage` or `httpOnly` cookie. Long-lived (7 days default).

### TypeScript Types

```ts
// src/lib/api-types.ts

interface ApiSuccess<T> {
  status: "success";
  data: T;
  message?: string;
}

interface PaginationMeta {
  page: number;
  limit: number;
  totalItems: number;
  totalPages: number;
}

interface PaginatedSuccess<T> {
  status: "success";
  data: T[];
  pagination: PaginationMeta;
}

interface ApiError {
  status: "error";
  error: {
    code: string;
    message: string;
    details: unknown[];
  };
}

type ApiResponse<T> = ApiSuccess<T> | ApiError;
```

---

## 3. Authentication Endpoints

All bodies use **camelCase** keys.

### Register — `POST /api/v1/auth/register`

```json
// Request
{
  "email": "user@example.com",
  "password": "Str0ngPass",
  "passwordConfirm": "Str0ngPass",
  "name": "Shelfwise Corp"
}

// Response → data
{
  "accessToken": "eyJ...",
  "refreshToken": "eyJ...",
  "tokenType": "bearer"
}
```

**Password rules**: ≥ 8 chars, at least 1 uppercase, 1 lowercase, 1 digit.
**Name**: Required string for the user or business name.

### Login — `POST /api/v1/auth/login`

```json
// Request
{ "email": "user@example.com", "password": "Str0ngPass" }

// Response → same TokenResponse shape as register
```

### Refresh — `POST /api/v1/auth/refresh`

```json
// Request
{ "refreshToken": "eyJ..." }

// Response → new TokenResponse
```

### Get Current User — `GET /api/v1/auth/me` 🔒

```json
// Response → data
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "Shelfwise Corp",
  "defaultForecastPeriod": 3,
  "defaultConfidenceLevel": "95",
  "holidayCalendar": "PH"
}
```

### Logout — `POST /api/v1/auth/logout` 🔒

Server-side is a no-op for MVP. Clear tokens client-side.

---

## 4. CSV Upload Wizard (3-Step Flow)

The backend stores pending bytes in PostgreSQL (`csv_upload_sessions`). Thread **`uploadSessionId`** through all steps.

Each session has a `status` field that tracks progress through the wizard:
- `"uploaded"` — Step 1 done, awaiting column mapping
- `"validated"` — Step 2 done, awaiting confirmation
- `"confirmed"` — Step 3 done, data imported

### Step 1 — Upload CSV: `POST /api/v1/upload/` 🔒

- Content-Type: `multipart/form-data`, field name `file`
- Max file size: **10 MB** · Max rows: **50 000**

```json
// Response → data
{
  "uploadSessionId": "uuid",
  "columns": ["date", "sku", "product_name", "qty"],
  "rowCount": 1250,
  "fileName": "sales.csv",
  "fileSizeMb": 0.45,
  "status": "uploaded",
  "suggestedMapping": {
    "date": { "csvColumn": "date", "confidence": "exact" },
    "product_id": { "csvColumn": "sku", "confidence": "high" },
    "quantity_sold": { "csvColumn": "qty", "confidence": "high" },
    "product_name": { "csvColumn": "product_name", "confidence": "exact" }
  },
  "unmappedCsvColumns": [],
  "requiredFields": ["date", "product_id", "quantity_sold"],
  "optionalFields": ["product_name"]
}
```

### Get Upload Session — `GET /api/v1/upload/{session_id}` 🔒

Returns session metadata (columns, suggested mapping, confidence, and the user's validated column mapping if available). Use this to populate the column mapping step when the user refreshes or navigates back.

```json
// Response → data
{
  "uploadSessionId": "uuid",
  "columns": ["date", "sku", "product_name", "qty"],
  "rowCount": 1250,
  "fileName": "sales.csv",
  "fileSizeMb": 0.45,
  "suggestedMapping": {
    "date": { "csvColumn": "date", "confidence": "exact" },
    "product_id": { "csvColumn": "sku", "confidence": "high" },
    "quantity_sold": { "csvColumn": "qty", "confidence": "high" },
    "product_name": { "csvColumn": "product_name", "confidence": "exact" }
  },
  "confidence": { "date": "exact", "product_id": "high", "quantity_sold": "high", "product_name": "exact" },
  "columnMap": {
    "date": "date",
    "product_id": "sku",
    "quantity_sold": "qty",
    "product_name": "product_name"
  },
  "status": "validated"
}
```

#### `columnMap` field

| Session Status | `columnMap` value |
|---|---|
| `"uploaded"` | `null` — validation hasn't been run yet, no user choices saved |
| `"validated"` | The `columnMap` object sent to `POST /upload/validate` |
| `"confirmed"` | The stored `columnMap` (session is deleted shortly after confirm) |

**Frontend usage**: When populating the mapping dropdowns on the column mapping step, prefer the user's validated choices over the auto-detected suggestions:

```ts
const mapping = session.columnMap ?? session.suggestedMapping;
```

This ensures that when the user navigates back from the validation step to the column mapping step, their manually-edited column choices are preserved instead of resetting to the auto-detected suggestions.

| Error Condition | HTTP | Code |
|---|---|---|
| Session not found / wrong user | 404 | `NOT_FOUND` |
| Session expired | 410 | `SESSION_EXPIRED` |

### Step 2 — Validate: `POST /api/v1/upload/validate` 🔒

```json
// Request
{
  "uploadSessionId": "uuid",
  "columnMap": {
    "date": "date",
    "product_id": "sku",
    "quantity_sold": "qty",
    "product_name": "product_name"
  }
}
```

Required map keys: `date`, `product_id`, `quantity_sold`. Optional: `product_name`.

Response `data` contains a rich preview object with:
- `products[]` — per-product summary (productId, name, existingRows, newRows, isNew, isSuspicious, action)
- `hasSuspicious` — flag to highlight products needing attention
- `qualityReport` — raw quality metrics
- `dataHealth` — health scorecard

### Get Validation Result — `GET /api/v1/upload/{session_id}/validation` 🔒

Returns the stored validation result (product preview, quality report). Use this to populate the review & confirm step when the user refreshes or navigates back. Requires `POST /upload/validate` to have been called first.

```json
// Response → data (same shape as POST /upload/validate response)
{
  "products": [
    {
      "productId": "SKU-001",
      "productName": "Widget A",
      "existingRows": 150,
      "newRows": 42,
      "isNew": false,
      "isSuspicious": false,
      "action": "replace"
    }
  ],
  "hasSuspicious": false,
  "qualityReport": { ... },
  "dataHealth": { ... }
}
```

| Error Condition | HTTP | Code |
|---|---|---|
| Session not found / wrong user | 404 | `NOT_FOUND` |
| Session expired | 410 | `SESSION_EXPIRED` |
| Validation not yet run | 404 | `NOT_FOUND` (message: "Validation has not been run for this session") |

### Step 3 — Confirm: `POST /api/v1/upload/confirm` 🔒

```json
// Request
{
  "uploadSessionId": "uuid",
  "skipProductIds": ["SKU-003"]  // optional: exclude specific products
}

// Response → data
{
  "totalRowsInserted": 1200,
  "productsCreated": 4,
  "productsUpdated": 2
}
```

### Template Download: `GET /api/v1/upload/template`

Returns a CSV file (`Content-Disposition: attachment`). No auth required.

### Route-Based Architecture

With the GET endpoints, the upload wizard becomes a set of **independent routes** — no React context, no reducer, no client-side state management needed:

```
/upload                → File drop step (POST /upload/)
/upload/mapping        → Column mapping (GET /upload/{id} via loader)
/upload/validation     → Review & confirm (GET /upload/{id}/validation via loader)
/upload/success        → Success (data from confirm response via nav state — one-time)
```

Each route (except success) has a **TanStack Router loader** that fetches its data from the GET endpoint. If the session is expired or missing, the loader redirects to `/upload`.

The `uploadSessionId` is passed between routes as a **search param** (`?session=uuid`). Use TanStack Router's `routeMasks` to keep the URL clean — the user always sees `/upload`.

### TypeScript Types

The existing `UploadSession` and `UploadValidation` types match the GET response shapes. Add these server functions:

```ts
// src/lib/queries.ts (add these)

export const uploadSessionQuery = (sessionId: string) =>
  queryOptions({
    queryKey: ["upload", "session", sessionId],
    queryFn: () => apiFetch(`/api/v1/upload/${sessionId}`),
    retry: false,  // don't retry on 404/410
  });

export const uploadValidationQuery = (sessionId: string) =>
  queryOptions({
    queryKey: ["upload", "validation", sessionId],
    queryFn: () => apiFetch(`/api/v1/upload/${sessionId}/validation`),
    retry: false,
  });
```

```ts
// src/routes/_auth/upload/mapping.tsx (example loader)
export const Route = createFileRoute("/_auth/upload/mapping")({
  validateSearch: z.object({ session: z.string().uuid() }),
  beforeLoad: async ({ search, context }) => {
    try {
      await context.queryClient.ensureQueryData(
        uploadSessionQuery(search.session)
      );
    } catch {
      throw redirect({ to: "/upload" });
    }
  },
  component: MappingStep,
});
```

### UX Notes

- Disable **Validate** button until Step 1 succeeds; disable **Confirm** until Step 2 succeeds.
- On `SESSION_EXPIRED` (410) errors, reset the wizard and show a "session expired" message.
- On `NOT_FOUND` (404) errors, redirect to the file upload step.
- Sessions expire after `UPLOAD_SESSION_TTL_HOURS` (default **24 hours**).
- Show the column auto-mapping suggestions from Step 1 pre-filled in a mapping UI. Let users override before calling Validate.
- **When navigating back to the mapping step**, use `session.columnMap ?? suggestedMapping` to pre-fill dropdowns with the user's validated choices (if available) instead of resetting to auto-detected suggestions.
- The `status` field on the session can be used to redirect users to the correct step if they revisit with a stale `session` search param.

---

## 5. Products

### List Products — `GET /api/v1/products/` 🔒

Query params: `page`, `limit` (1–100), `category`, `isArchived` (default `false`).

```json
// Response → paginated
// Each item:
{
  "id": "uuid (internal)",
  "productId": "SKU-001 (from CSV)",
  "name": "Widget A",
  "category": "Electronics",
  "description": null,
  "isArchived": false,
  "createdAt": "2025-01-01T00:00:00+00:00"
}
```

> [!IMPORTANT]
> **`id`** is the internal UUID used in all API calls (e.g. creating forecasts).
> **`productId`** is the business SKU string from the CSV. Display `productId` to the user, but send `id` when calling the API.

### Get Product — `GET /api/v1/products/{id}` 🔒

Returns the same shape plus `notes` and `updatedAt`.

### Update Product — `PATCH /api/v1/products/{id}` 🔒

Editable fields: `category`, `description`, `notes`.

```json
// Request (partial update)
{ "category": "Beverages", "description": "Updated description" }
```

### Archive/Unarchive — `PATCH /api/v1/products/{id}/archive` 🔒

Toggles `isArchived`. No request body needed.

```json
// Response → data
{ "id": "uuid", "isArchived": true }
```

---

## 6. Forecasts

### Create Forecast — `POST /api/v1/forecasts/` 🔒

```json
// Request
{
  "productId": "uuid (internal product UUID, NOT the SKU string)",
  "horizonDays": 90,
  "timeGranularity": "daily",       // "daily" | "weekly" | "monthly"
  "confidenceLevel": "95",          // "80" | "95" | "both"
  "enableTuning": false,
  "tuneTrials": 30,
  "country": "PH"                   // optional, for holiday effects
}

// Response → data (immediate)
{ "id": "uuid", "status": "processing" }
```

### Poll for Completion — `GET /api/v1/forecasts/{id}` 🔒

Use capped exponential backoff: 1s → 2s → 4s → 8s → … cap at 10s. Max total wait ≈ 5 min.

```json
// Response → data
{
  "id": "uuid",
  "productId": "uuid",
  "forecastDate": "2025-06-15T12:00:00+00:00",
  "forecastHorizon": 90,
  "timeGranularity": "daily",
  "confidenceLevel": "95",
  "seasonalityMode": "additive",
  "selectedModel": "prophet",
  "demandProfile": "smooth",
  "status": "processing",       // "processing" | "generating_explanation" | "completed" | "failed"
  "progressStep": 2,            // current step (nullable)
  "progressTotal": 5,           // total steps (nullable)
  "progressLabel": "Training model...",  // human-readable label (nullable)
  "mape": 12.5,                 // metrics available once status is "generating_explanation" or "completed"
  "wape": 10.2,
  "smape": 11.8,
  "mase": 0.85,
  "rmse": 45.2,
  "mae": 38.1,
  "dataStartDate": "2024-01-01",
  "dataEndDate": "2025-06-15",
  "dataRowCount": 530,
  "modelParameters": { "enableTuning": false, "tuneTrials": 30 },
  "tunedParameters": { ... },    // null if tuning disabled
  "aiExplanation": null,         // null until status === "completed" (see two-phase UX below)
  "errorMessage": null            // set when status === "failed"
}
```

**Two-Phase Display UX**:

The forecast pipeline commits results to the database **before** calling the AI explanation service (Gemini). This means charts, metrics, and components are available as soon as `status` transitions to `"generating_explanation"` — you don't need to wait for `"completed"`.

| Status | What's ready | Frontend action |
|--------|-------------|-----------------|
| `"processing"` | Nothing | Show progress bar with `progressStep` / `progressTotal` and `progressLabel` |
| `"generating_explanation"` | ✅ Metrics, results, components | **Navigate to the report view.** Show all charts/metrics. Show a skeleton/shimmer for the AI explanation section. |
| `"completed"` | ✅ Everything + `aiExplanation` | Replace the skeleton with the AI explanation content. **Stop polling.** |
| `"failed"` | Error info | Display `errorMessage`. Stop polling. |

```ts
// Determine when the forecast data is ready to display
const isReady = status === "generating_explanation" || status === "completed";

// Determine when the AI explanation is still loading
const isExplanationLoading = !forecast.aiExplanation;
```

> [!TIP]
> When `status === "generating_explanation"`, continue polling with a **slower interval** (e.g. 3–5s) since you're only waiting for the AI text — no need for aggressive backoff.

**Polling UX (progress bar phase)**:
- Show a progress bar using `progressStep` / `progressTotal`.
- Show `progressLabel` as descriptive text beneath the bar.
- When `status === "generating_explanation"` or `status === "completed"`, fetch results and navigate to the report view.
- When `status === "failed"`, display `errorMessage`.

### List Forecasts — `GET /api/v1/forecasts/` 🔒

Query params: `page`, `limit`, `productId` (optional UUID filter).

```json
// Each item:
{
  "id": "uuid",
  "productId": "uuid",
  "forecastDate": "...",
  "forecastHorizon": 90,
  "selectedModel": "prophet",
  "demandProfile": "smooth",
  "mape": 12.5,
  "status": "completed"
}
```

### Forecast Results — `GET /api/v1/forecasts/{id}/results` 🔒

```json
// Response → data (array)
[
  {
    "date": "2025-06-16",
    "predictedValue": 42.5,
    "lowerBound80": 35.0,
    "upperBound80": 50.0,
    "lowerBound95": 28.0,
    "upperBound95": 57.0,
    "trend": 40.1,
    "weeklySeasonality": 2.3,
    "yearlySeasonality": 0.1
  }
]
```

Use this data for charts. `lowerBound80`/`upperBound80` and `lowerBound95`/`upperBound95` render as confidence interval bands.

### Forecast Components — `GET /api/v1/forecasts/{id}/components` 🔒

```json
// Response → data
{
  "trend": [{ "date": "2025-06-16", "value": 40.1 }, ...],
  "weekly": [{ "dayOfWeek": "Monday", "effect": 2.3 }, ...],
  "yearly": [{ "month": "January", "effect": -1.2 }, ...]
}
```

### Exports

All exports require `status === "completed"`. Each returns a file download.

| Endpoint | Content-Type | Triggers |
|----------|-------------|----------|
| `GET /api/v1/forecasts/{id}/export/csv` 🔒 | `text/csv` | Browser download |
| `GET /api/v1/forecasts/{id}/export/chart` 🔒 | `image/png` | Browser download |
| `GET /api/v1/forecasts/{id}/export/pdf` 🔒 | `application/pdf` | Browser download |

**Download pattern**: open the URL in a new tab, or use `fetch` + `Blob` + `URL.createObjectURL` to trigger a download without navigating away. Remember to include the `Authorization` header.

```ts
// Example download helper
async function downloadExport(forecastId: string, format: "csv" | "chart" | "pdf") {
  const res = await apiFetch(`/api/v1/forecasts/${forecastId}/export/${format}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = res.headers.get("Content-Disposition")?.split("filename=")[1] ?? `export.${format === "chart" ? "png" : format}`;
  a.click();
  URL.revokeObjectURL(url);
}
```

---

## 7. Sharing (Public Links)

### Check Share Status — `GET /api/v1/forecasts/{id}/share` 🔒

Returns whether a forecast is currently shared. Use this to conditionally render the **Revoke** button in the share UI.

The endpoint considers a forecast "shared" only if it has a valid `shareToken` **and** the link has not expired (when an expiry is set).

```json
// Response → data
{
  "isShared": true,
  "shareToken": "abc123...",       // null if not shared
  "expiresAt": "2025-06-18T12:00:00+00:00"  // null if no expiry or not shared
}
```

**TanStack Query:**

```ts
// src/lib/queries.ts (add this)
export const forecastShareStatusQuery = (forecastId: string) =>
  queryOptions({
    queryKey: ["forecast", forecastId, "share"],
    queryFn: () => apiFetch(`/api/v1/forecasts/${forecastId}/share`),
  });
```

**Frontend usage — conditional Revoke button:**

```tsx
const { data: shareStatus } = useQuery(forecastShareStatusQuery(forecastId));

// Show the Revoke button only when the forecast has an active share link
{shareStatus?.data?.isShared && (
  <Button variant="destructive" onClick={handleRevoke}>
    Revoke Link
  </Button>
)}
```

> [!TIP]
> After creating or revoking a share link, invalidate the share status query so the UI updates immediately:
> ```ts
> queryClient.invalidateQueries({ queryKey: ["forecast", forecastId, "share"] });
> ```

### Create Share Link — `POST /api/v1/forecasts/{id}/share` 🔒

```json
// Request (optional body)
{ "expiresInHours": 72 }   // null or 0 = never expires

// Response → data
{
  "shareToken": "abc123...",
  "shareUrl": "/api/v1/shared/forecasts/abc123...",
  "expiresAt": "2025-06-18T12:00:00+00:00"  // null if no expiry
}
```

### Revoke Share Link — `DELETE /api/v1/forecasts/{id}/share` 🔒

No request body. Clears token and expiry.

### View Shared Forecast — `GET /api/v1/shared/forecasts/{token}` (public, no auth)

Returns a rich read-only payload:

```json
// Response → data
{
  "forecast": {
    "id": "uuid",
    "forecastDate": "...",
    "forecastHorizon": 90,
    "timeGranularity": "daily",
    "confidenceLevel": "95",
    "selectedModel": "prophet",
    "demandProfile": "smooth",
    "seasonalityMode": "additive",
    "status": "completed",
    "progressStep": null,
    "progressTotal": null,
    "progressLabel": null,
    "metrics": {
      "mape": 12.5, "wape": 10.2, "smape": 11.8,
      "mase": 0.85, "rmse": 45.2, "mae": 38.1
    },
    "dataStartDate": "2024-01-01",
    "dataEndDate": "2025-06-15",
    "dataRowCount": 530,
    "aiExplanation": "..."
  },
  "product": {
    "productId": "SKU-001",
    "name": "Widget A",
    "category": "Electronics"
  },
  "results": [ /* same shape as /results endpoint */ ]
}
```

The shared view should be a **separate route** in TanStack Router (e.g. `/shared/$token`) that renders a read-only forecast report without requiring login.


---

## 8. Shelfwise Advisor (AI Chatbot)

The chatbot is branded as **"Shelfwise Advisor"** — a friendly, non-technical AI assistant that helps business owners understand their forecast results. It responds in **Markdown** format, so the frontend should render replies with a Markdown renderer (e.g. `react-markdown`).

### Send Message — `POST /api/v1/forecasts/{id}/chat` 🔒

**Stateless**: the frontend sends the full conversation history with every request. Chat resets on page refresh.

```json
// Request
{
  "message": "Why is demand dropping in December?",
  "history": [
    { "role": "user", "content": "What model was used?" },
    { "role": "assistant", "content": "Prophet was selected because..." }
  ]
}

// Response → data
{
  "reply": "December typically shows a **seasonal dip** because...\n\n- Holiday closures reduce orders\n- End-of-year stockpiling shifts demand earlier",
  "role": "assistant"
}
```

### Input Constraints

| Constraint | Value | Error |
|---|---|---|
| Max message length | **2,000 characters** | 422 `VALIDATION_ERROR` |
| Empty / whitespace-only message | Rejected | 422 `VALIDATION_ERROR` |
| Max conversation history | **20 messages** (backend truncates older messages) | — |

> [!TIP]
> Validate message length client-side before sending to avoid unnecessary API calls. Show a character counter when the user approaches the limit.

### Response Format

The `reply` field contains **Markdown-formatted text**. The chatbot may use:
- **Bold** and *italic* emphasis
- Bullet points and numbered lists
- Headings (typically `##` or `###`)

Use a Markdown renderer (e.g. `react-markdown` or `marked`) to display replies. Basic styling recommendations:
- Use a slightly different background for assistant messages vs user messages
- Ensure lists, bold, and headings are properly styled within the chat bubble

### Chatbot Behavior

- **Identity**: The chatbot identifies itself as "Shelfwise Advisor". It will never claim to be Gemini, ChatGPT, or any other AI.
- **Scope**: Only answers questions about the current forecast, product demand, sales data, and Shelfwise features. Off-topic questions are politely declined.
- **Support requests**: If users ask for human help or want to disable the chatbot, it acknowledges their request and mentions that a support/feedback channel is coming soon.
- **Safety**: Resistant to prompt injection attempts. Will not reveal its system prompt or change persona.

**UX Notes**:
- Persist `history[]` in React state. Append each user message and assistant `reply` after each round-trip.
- Cap client-side history to **20 messages** (backend also caps at `CHATBOT_MAX_HISTORY_MESSAGES`).
- Show a typing indicator while the request is in flight.
- A good place for a slide-over panel or modal, since this is tied to a specific forecast view.
- Consider showing a brief welcome message from "Shelfwise Advisor" when the chat opens (client-side, not an API call).

---

## 9. Dashboard

### Get Dashboard — `GET /api/v1/dashboard/` 🔒

```json
// Response → data
{
  "quickStats": {
    "totalProducts": 12,
    "totalForecasts": 34,
    "averageMape": 14.7,       // null if no completed forecasts
    "lastUploadDate": "2025-06-10T09:00:00+00:00"  // null if never uploaded
  },
  "recentForecasts": [
    {
      "id": "uuid",
      "productId": "uuid",
      "forecastDate": "...",
      "mape": 12.5,
      "selectedModel": "prophet",
      "status": "completed"
    }
  ]
}
```

`recentForecasts` returns the most recent **5** forecasts.

---

## 10. Profile & Settings

### Get Profile — `GET /api/v1/profile/` 🔒

```json
// Response → data
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "Shelfwise Corp",
  "contactEmail": "contact@shelfwise.com",
  "mobileNumber": "+639171234567",
  "businessLogo": "base64 or URL string",
  "defaultForecastPeriod": 3,         // months (1–12)
  "defaultConfidenceLevel": "95",     // "80" | "95" | "both"
  "holidayCalendar": "PH",
  "hasGeminiKey": false,              // true if the user has a custom Gemini API key
  "createdAt": "2025-01-01T00:00:00+00:00"
}
```

### Update Profile — `PATCH /api/v1/profile/` 🔒

Partial update. Accepts camelCase keys:

```json
{ "name": "New Name", "defaultForecastPeriod": 6 }
```

Allowed fields: `name`, `contactEmail`, `mobileNumber`, `businessLogo`, `defaultForecastPeriod`, `defaultConfidenceLevel`, `holidayCalendar`.

### Change Password — `PUT /api/v1/profile/password` 🔒

```json
{ "currentPassword": "OldStr0ng", "newPassword": "NewStr0ng1" }
```

Same password rules as register (≥ 8 chars, 1 upper, 1 lower, 1 digit).

### Get Holidays — `GET /api/v1/profile/holidays` 🔒

```json
// Response → data
{
  "holidayCalendar": "PH",
  "supportedCountries": [
    { "code": "AR", "name": "Argentina" },
    { "code": "AU", "name": "Australia" },
    { "code": "BD", "name": "Bangladesh" },
    ...
  ]
}
```

> [!NOTE]
> `supportedCountries` is sorted alphabetically by `name`. Display `name` in the UI (e.g. select dropdown label) and send `code` as the value to `PUT /profile/holidays`.

### Update Holidays — `PUT /api/v1/profile/holidays` 🔒

```json
{ "holidayCalendar": "US" }
```

### List Built-in Holidays — `GET /api/v1/profile/holidays/builtin` 🔒

Returns the explicit list of holidays that come "out of the box" from the user's currently selected country calendar. Powered by the Python `holidays` library (same source Prophet uses for forecasting).

Query params: `year` (int, defaults to current year).

```json
// GET /api/v1/profile/holidays/builtin?year=2026
// Response → data
{
  "country": "PH",
  "year": 2026,
  "holidays": [
    { "date": "2026-01-01", "name": "New Year's Day" },
    { "date": "2026-02-17", "name": "Chinese New Year" },
    { "date": "2026-04-02", "name": "Maundy Thursday" },
    { "date": "2026-04-03", "name": "Good Friday" },
    { "date": "2026-04-09", "name": "Day of Valor" },
    { "date": "2026-05-01", "name": "Labor Day" },
    { "date": "2026-06-12", "name": "Independence Day" },
    { "date": "2026-12-25", "name": "Christmas Day" }
  ]
}
```

> [!NOTE]
> The holidays returned depend on the user's `holidayCalendar` setting. Changing the country code (via `PUT /profile/holidays`) will change which built-in holidays are shown.

### List Custom Holidays — `GET /api/v1/profile/holidays/custom` 🔒

Returns the user's manually-created custom holidays.

Query params: `year` (int, optional — omit to return all years).

```json
// Response → data (array)
[
  {
    "id": "uuid",
    "name": "Company Anniversary",
    "date": "2026-06-15",
    "createdAt": "2026-03-30T10:00:00+00:00",
    "updatedAt": null
  }
]
```

### Create Custom Holiday — `POST /api/v1/profile/holidays/custom` 🔒

```json
// Request
{ "name": "Company Anniversary", "date": "2026-06-15" }

// Response (201) → data
{
  "id": "uuid",
  "name": "Company Anniversary",
  "date": "2026-06-15",
  "createdAt": "2026-03-30T10:00:00+00:00"
}
```

**Validation rules:**
- `name` must be non-empty
- `date` must be valid ISO format (`YYYY-MM-DD`)
- `date` must **not** overlap with a built-in holiday for the user's country (returns 422: *"June 12 is already a built-in holiday: Independence Day"*)
- `date` must **not** already be used by another custom holiday for this user (returns 422: *"You already have a custom holiday on 2026-06-15: ..."*)

### Update Custom Holiday — `PUT /api/v1/profile/holidays/custom/{id}` 🔒

Partial update — send only the fields you want to change.

```json
// Request (partial)
{ "name": "Updated Name" }
// or
{ "date": "2026-07-01" }
// or both
{ "name": "Updated Name", "date": "2026-07-01" }

// Response → data
{
  "id": "uuid",
  "name": "Updated Name",
  "date": "2026-07-01",
  "updatedAt": "2026-03-30T12:00:00+00:00"
}
```

Same validation as create (no built-in collision, no duplicate date).

### Delete Custom Holiday — `DELETE /api/v1/profile/holidays/custom/{id}` 🔒

No request body. Returns 404 if the holiday doesn't exist or doesn't belong to the user.

```json
// Response → data: null, message: "Custom holiday deleted"
```

### TypeScript Types for Holidays

```ts
// src/lib/api-types.ts (add to existing types)

interface SupportedCountry {
  code: string;   // ISO 3166-1 alpha-2 (e.g. "PH") — send this to the API
  name: string;   // Full display name (e.g. "Philippines") — show this in UI
}

interface BuiltinHoliday {
  date: string;   // "YYYY-MM-DD"
  name: string;
}

interface BuiltinHolidaysResponse {
  country: string;
  year: number;
  holidays: BuiltinHoliday[];
}

interface CustomHoliday {
  id: string;
  name: string;
  date: string;   // "YYYY-MM-DD"
  createdAt: string | null;
  updatedAt: string | null;
}

interface CreateCustomHolidayRequest {
  name: string;
  date: string;   // "YYYY-MM-DD"
}

interface UpdateCustomHolidayRequest {
  name?: string;
  date?: string;   // "YYYY-MM-DD"
}
```

### TanStack Query — Holiday Queries

```ts
// src/lib/queries.ts (add these)

export const builtinHolidaysQuery = (year: number) =>
  queryOptions({
    queryKey: ["holidays", "builtin", year],
    queryFn: () => apiFetch(`/api/v1/profile/holidays/builtin?year=${year}`),
  });

export const customHolidaysQuery = (year?: number) =>
  queryOptions({
    queryKey: ["holidays", "custom", year ?? "all"],
    queryFn: () => {
      const params = year ? `?year=${year}` : "";
      return apiFetch(`/api/v1/profile/holidays/custom${params}`);
    },
  });
```

### Calendar UX Notes

- **Visual distinction**: Render built-in holidays with a distinct style (e.g., muted color, "System" badge) versus custom holidays (user's accent color, editable).
- **Prevent redundancy**: Before opening the "add custom holiday" dialog, check the date against the built-in list and show a warning or disable the action if it collides.
- **Invalidate on country change**: When the user changes their holiday calendar country code (`PUT /profile/holidays`), invalidate both `["holidays", "builtin"]` and potentially show a notification that some custom holidays may now overlap with the new country's built-in holidays.
- **Invalidate on CRUD**: After creating, updating, or deleting a custom holiday, invalidate `["holidays", "custom"]`.
- **Forecasting impact**: Both built-in and custom holidays are automatically factored into the Prophet forecasting model. No extra action is needed when creating forecasts — the backend picks them up from the database.

### Gemini API Key — `GET /api/v1/profile/gemini-key` 🔒

Check whether the user has a custom Gemini API key configured. The full key is **never** returned — only a masked preview.

```json
// Response → data (when key is set)
{
  "hasKey": true,
  "keyPreview": "AIza...xOQU",
  "addedAt": "2026-04-09T09:30:00+00:00"
}

// Response → data (when no key is set)
{
  "hasKey": false,
  "keyPreview": null,
  "addedAt": null
}
```

> [!NOTE]
> You can also check `hasGeminiKey` from the `GET /profile` response to avoid an extra API call when you just need a boolean.

### Set Gemini API Key — `PUT /api/v1/profile/gemini-key` 🔒

Add or replace the user's custom Gemini API key. The backend **validates the key** by making a test API call before storing it.

```json
// Request
{ "apiKey": "AIzaSy..." }

// Response → data
{
  "hasKey": true,
  "keyPreview": "AIza...xOQU",
  "addedAt": "2026-04-09T09:30:00+00:00"
}
```

**Validation errors:**
- `apiKey` is required (422 `VALIDATION_ERROR`)
- Key too short (422 `VALIDATION_ERROR`)
- Key is invalid / fails test call (422 `VALIDATION_ERROR`: *"The API key is invalid. Please check your key and try again."*)

> [!TIP]
> The validation call may take 1–3 seconds. Show a loading spinner on the save button while the request is in flight.

### Delete Gemini API Key — `DELETE /api/v1/profile/gemini-key` 🔒

Remove the user's custom key. After deletion, AI features (chatbot, forecast explanations) fall back to the server's default API key.

```json
// Response → data: null, message: "Gemini API key removed"
```

Returns 404 if no key is configured.

### How the Key is Used

Once a custom key is saved, it's automatically used for:
- **Forecast AI explanations** — generated during the forecasting pipeline
- **Shelfwise Advisor (chatbot)** — all chat messages use the user's key

If no custom key is set, these features fall back to the server's default `GEMINI_API_KEY` from `.env`. If neither is configured, AI features are unavailable.

### TypeScript Types

```ts
// src/lib/api-types.ts (add to existing types)

interface GeminiKeyStatus {
  hasKey: boolean;
  keyPreview: string | null;
  addedAt: string | null;
}

interface SetGeminiKeyRequest {
  apiKey: string;
}
```

### TanStack Query — Gemini Key

```ts
// src/lib/queries.ts (add this)

export const geminiKeyQuery = () =>
  queryOptions({
    queryKey: ["profile", "gemini-key"],
    queryFn: () => apiFetch("/api/v1/profile/gemini-key"),
  });
```

### UX Notes

- **Settings page**: Add a "Gemini API Key" card in the settings/profile page. Show the masked preview when a key is set, with "Replace" and "Remove" actions.
- **Input masking**: Use a password-type input for the API key field. Show a toggle to reveal the key while typing.
- **Invalidate on change**: After saving or deleting a key, invalidate `["profile", "gemini-key"]` and `["profile"]`.
- **AI availability indicator**: Use `hasGeminiKey` from the profile (or `hasKey` from the gemini-key endpoint) to show whether AI features are available. If neither the user nor the server has a key configured, show a callout prompting the user to add their own key.

---

## 11. Health Check

### `GET /api/v1/health` (public)

```json
{
  "status": "healthy",       // "healthy" | "degraded"
  "version": "1.0.0",
  "timestamp": "2025-06-15T12:00:00+00:00",
  "checks": { "database": "connected" }
}
```

Use for connection-status indicators in the app.

---

## 12. SPA Architecture Notes

### Route Structure (TanStack Router — URL-Routed Modals)

Every modal/panel gets its **own URL path** so browser back/forward navigation works naturally. The trick is using TanStack Router's **layout routes**: the dashboard stays rendered in the background while modals render as overlays via child routes.

```
src/routes/
├── __root.tsx                 # Root layout + auth guard
├── _auth.tsx                  # Authenticated layout (sidebar + main)
├── _auth/
│   ├── index.tsx              # Dashboard (home — always visible behind modals)
│   ├── products/
│   │   ├── index.tsx          # Products list modal/panel
│   │   └── $productId.tsx     # Product detail modal
│   ├── forecasts/
│   │   ├── index.tsx          # Forecast history list modal/panel
│   │   ├── $forecastId.tsx    # Forecast detail/report modal
│   │   └── $forecastId.chat.tsx  # Chatbot slide-over (within forecast)
│   ├── upload.tsx             # Upload wizard modal (multi-step)
│   └── settings.tsx           # Profile/settings modal
├── login.tsx                  # Login page (public)
├── register.tsx               # Register page (public)
└── shared/
    └── $token.tsx             # Public shared forecast (no auth)
```

**Key pattern**: The `_auth.tsx` layout route renders the dashboard content **plus** an `<Outlet />` where child route components render as modals on top. Navigating to `/products/abc-123` shows the dashboard with the product detail modal overlaid. Pressing the browser back button closes the modal (navigates back to `/`).

```tsx
// src/routes/_auth.tsx (simplified)
export const Route = createFileRoute("/_auth")({
  component: AuthLayout,
});

function AuthLayout() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Dashboard />          {/* Always visible */}
        <Outlet />             {/* Modals render here */}
      </main>
    </div>
  );
}
```

### Modal/Panel Strategy (SilkHQ — manual wiring)

Each route component (e.g. `$productId.tsx`) renders a SilkHQ modal that's always in the "open" state. When the modal's `onClose` fires, navigate back:

```tsx
// src/routes/_auth/products/$productId.tsx (simplified)
import { useNavigate } from "@tanstack/react-router";

export const Route = createFileRoute("/_auth/products/$productId")({
  component: ProductDetailModal,
});

function ProductDetailModal() {
  const { productId } = Route.useParams();
  const navigate = useNavigate();

  return (
    <Modal open onClose={() => navigate({ to: "/" })}>
      <ProductDetail id={productId} />
    </Modal>
  );
}
```

Use **React state** only for ephemeral sub-dialogs (confirmations, dropdown menus) that don't need their own URL.

### Auth Guard

Place the guard in `__root.tsx` or `_auth.tsx` via `beforeLoad`:

```ts
// src/routes/_auth.tsx
export const Route = createFileRoute("/_auth")({
  beforeLoad: async () => {
    if (!getAccessToken()) {
      throw redirect({ to: "/login" });
    }
  },
  component: AuthLayout,
});
```

Public routes (`/login`, `/register`, `/shared/$token`) live outside the `_auth` layout and skip the guard entirely.

### Data Fetching — TanStack Query + Route Loaders

Combine `queryOptions` definitions with route `beforeLoad` / `loader` using `ensureQueryData`. This gives you:
- **Route-level prefetching** — data loads before the component renders (no loading flash).
- **TanStack Query caching** — subsequent navigations to the same route serve from cache instantly.
- **Background refetches** — stale data is refreshed automatically.

```ts
// src/lib/queries.ts — define query options once, reuse everywhere
import { queryOptions } from "@tanstack/react-query";
import { apiFetch } from "./api";

export const dashboardQuery = () =>
  queryOptions({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch("/api/v1/dashboard/"),
  });

export const productsQuery = (page = 1) =>
  queryOptions({
    queryKey: ["products", page],
    queryFn: () => apiFetch(`/api/v1/products/?page=${page}`),
  });

export const forecastQuery = (id: string) =>
  queryOptions({
    queryKey: ["forecast", id],
    queryFn: () => apiFetch(`/api/v1/forecasts/${id}`),
  });

export const forecastResultsQuery = (id: string) =>
  queryOptions({
    queryKey: ["forecast", id, "results"],
    queryFn: () => apiFetch(`/api/v1/forecasts/${id}/results`),
  });
```

```ts
// src/routes/_auth/forecasts/$forecastId.tsx — use in route loader
export const Route = createFileRoute("/_auth/forecasts/$forecastId")({
  beforeLoad: async ({ params, context }) => {
    // context.queryClient is provided by the root route
    await context.queryClient.ensureQueryData(forecastQuery(params.forecastId));
    await context.queryClient.ensureQueryData(forecastResultsQuery(params.forecastId));
  },
  component: ForecastDetailModal,
});

function ForecastDetailModal() {
  const { forecastId } = Route.useParams();
  // Data is already in cache from beforeLoad — renders instantly
  const { data: forecast } = useSuspenseQuery(forecastQuery(forecastId));
  const { data: results } = useSuspenseQuery(forecastResultsQuery(forecastId));
  // ...
}
```

**Providing `queryClient` to routes**:

```ts
// src/routes/__root.tsx
import { QueryClient } from "@tanstack/react-query";

const queryClient = new QueryClient();

export const Route = createRootRoute({
  context: () => ({ queryClient }),
  component: RootLayout,
});
```

### Polling with TanStack Query

```ts
const { data } = useQuery({
  queryKey: ["forecast", forecastId],
  queryFn: () => apiFetch(`/api/v1/forecasts/${forecastId}`),
  refetchInterval: (query) => {
    const status = query.state.data?.data?.status;
    if (status === "completed" || status === "failed") return false;
    return 3000; // poll every 3s while processing
  },
});
```

### Key TailwindCSS Conventions

- Use Tailwind utility classes exclusively — no custom CSS classes.
- All component styling via `className` props with Tailwind.
- Use Tailwind's built-in responsive prefixes (`sm:`, `md:`, `lg:`) for layout breakpoints.
- Use `dark:` prefix for dark mode support if desired.

---

## 13. CORS

The backend's default `CORS_ORIGINS` is `["http://localhost:3000"]`. If developing on a different port, update the backend `.env`:

```
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```
