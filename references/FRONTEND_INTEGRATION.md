# Frontend integration (ShelfWise API)

This document complements the backend in `shelfwise-api`. Implement these patterns in your SPA (e.g. Next.js) against `/api/v1`.

## 1. Auth-aware HTTP client

- Send `Authorization: Bearer <accessToken>` on every protected request.
- On **401**, call `POST /api/v1/auth/refresh` with the stored refresh token, update the access token, and retry the request once.
- If refresh fails, clear local auth state and redirect to login.

This avoids losing an in-progress CSV wizard when the access token expires mid-flow.

## 2. CSV upload wizard (three steps)

The backend stores pending bytes in PostgreSQL (`csv_upload_sessions`). The client must thread **`uploadSessionId`** through all steps.

| Step | Method | Body | Client keeps |
|------|--------|------|----------------|
| 1 | `POST /upload/` | `multipart/form-data`, field `file` | `uploadSessionId` from `data.uploadSessionId` |
| 2 | `POST /upload/validate` | JSON: `uploadSessionId`, `columnMap` | Preview from `data` |
| 3 | `POST /upload/confirm` | JSON: `uploadSessionId`, optional `skipProductIds` | Commit summary from `data` |

UX:

- Disable validate until step 1 succeeds; disable confirm until step 2 succeeds.
- On validation errors such as an unknown session or expiry, reset the wizard and ask the user to upload again (you may keep the `File` in memory to re-post step 1 without re-picking).

Sessions expire after **`UPLOAD_SESSION_TTL_HOURS`** (default 24), configurable on the server.

## 3. Product UUID for forecasts

- `GET /api/v1/products` returns each product’s internal **`id`** (UUID) and business **`productId`** (SKU string).
- `POST /api/v1/forecasts` expects **`productId`** in the JSON body to be that **internal UUID**, not the CSV SKU string.
- Build a map from SKU → UUID after listing products so the UI can label by SKU while calling the API with UUIDs.

## 4. Async forecast job + results

1. `POST /forecasts` returns immediately with `{ id, status: "processing" }`.
2. Poll `GET /forecasts/{id}` with capped exponential backoff (e.g. 1s → 2s → 5s) and a maximum wait (e.g. 3–5 minutes).
3. When `status === "completed"`, load series from `GET /forecasts/{id}/results` (optional: `/components`, export endpoints).
4. When `status === "failed"`, show `errorMessage` from the forecast detail response.

## 5. Paginated list responses

List endpoints wrap items in:

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

Use **`totalItems`** and **`totalPages`** (camelCase), not snake_case.
