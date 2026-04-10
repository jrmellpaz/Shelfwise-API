# Backend Enhancement: Upload Session GET Endpoints

## Motivation

The current upload wizard requires passing API response data between frontend steps via client-side state (React context, reducer, or navigation state). If the user refreshes the page mid-wizard, all progress is lost because there are no GET endpoints to re-fetch session/validation data.

Adding two GET endpoints makes each wizard step **self-contained** — the frontend can fetch everything it needs from the `uploadSessionId` alone, enabling clean route-based architecture with loaders.

---

## Required Endpoints

### 1. `GET /api/v1/upload/{session_id}` 🔒

Returns the session metadata created during Step 1. This allows the **column mapping step** to independently load the detected columns, suggested mapping, and confidence scores.

**When it's called**: Frontend navigates to the mapping step with just the `session_id` in the URL/state.

#### Response

Same shape as the existing `POST /upload/` response:

```json
{
  "status": "success",
  "data": {
    "uploadSessionId": "uuid",
    "columns": ["date", "sku", "product_name", "qty"],
    "rowCount": 1250,
    "fileName": "sales.csv",
    "fileSizeMb": 0.45,
    "suggestedMapping": {
      "date": "date",
      "product_id": "sku",
      "quantity_sold": "qty",
      "product_name": "product_name"
    },
    "confidence": { "date": 0.95, "product_id": 0.80 },
    "status": "uploaded"
  }
}
```

#### Implementation Notes

- **No new data needed** — all fields (`columns`, `suggestedMapping`, `confidence`, `fileName`, `fileSizeMb`, `rowCount`) should already be stored in the `csv_upload_sessions` table from when `POST /upload/` was called.
- If columns/mapping/confidence are not currently persisted, **add JSONB columns** to the `csv_upload_sessions` table:
  ```sql
  ALTER TABLE csv_upload_sessions
    ADD COLUMN columns_detected JSONB,
    ADD COLUMN suggested_mapping JSONB,
    ADD COLUMN confidence JSONB;
  ```
  Populate these during the existing `POST /upload/` handler.
- **Authorization**: Verify `session.user_id == current_user.id`. Return 404 if session doesn't exist or doesn't belong to the user.
- **Expiry check**: Return 404 (or 410 Gone) if the session has expired (older than `UPLOAD_SESSION_TTL_HOURS`).
- **New field — `status`**: Add a `status` column to track where in the wizard the session is:
  ```
  "uploaded"   → Step 1 done, awaiting column mapping
  "validated"  → Step 2 done, awaiting confirmation  
  "confirmed"  → Step 3 done, data imported
  "expired"    → Session expired
  ```
  This lets the frontend redirect to the correct step if the user revisits.

#### Error Cases

| Condition | HTTP | Error Code |
|---|---|---|
| Session not found | 404 | `NOT_FOUND` |
| Session belongs to another user | 404 | `NOT_FOUND` |
| Session expired | 410 | `SESSION_EXPIRED` |

---

### 2. `GET /api/v1/upload/{session_id}/validation` 🔒

Returns the **stored validation result** from Step 2. This allows the **validation/review step** to independently load the product preview, suspicious flags, and quality metrics.

**When it's called**: Frontend navigates to the validation step with just the `session_id`.

#### Prerequisite

`POST /upload/validate` must store its result in the database before returning. Currently it may compute and return the result without persisting it.

#### Response

Same shape as the existing `POST /upload/validate` response:

```json
{
  "status": "success",
  "data": {
    "products": [
      {
        "productId": "SKU-001",
        "name": "Widget A",
        "existingRows": 150,
        "newRows": 42,
        "isNew": false,
        "isSuspicious": false,
        "action": "append"
      }
    ],
    "hasSuspicious": false,
    "qualityReport": { ... },
    "dataHealth": { ... }
  }
}
```

#### Implementation Notes

- **Store validation result**: When `POST /upload/validate` runs, serialize the result to a JSONB column on `csv_upload_sessions`:
  ```sql
  ALTER TABLE csv_upload_sessions
    ADD COLUMN validation_result JSONB,
    ADD COLUMN column_map JSONB;
  ```
  Update the `status` to `"validated"` and save the `column_map` used (useful for debugging).
- **GET handler**: Simply read `validation_result` from the session row and return it.
- **Guard**: If the session `status` is still `"uploaded"` (validation hasn't been run yet), return 404 with message "Validation has not been run for this session."
- **Authorization & expiry**: Same checks as the session GET endpoint.

#### Error Cases

| Condition | HTTP | Error Code |
|---|---|---|
| Session not found / wrong user | 404 | `NOT_FOUND` |
| Session expired | 410 | `SESSION_EXPIRED` |
| Validation not yet run | 404 | `NOT_FOUND` (message: "Validation has not been run for this session") |

---

## Database Changes Summary

Add the following columns to `csv_upload_sessions`:

```sql
ALTER TABLE csv_upload_sessions
  ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'uploaded',
  ADD COLUMN columns_detected JSONB,
  ADD COLUMN suggested_mapping JSONB,
  ADD COLUMN confidence JSONB,
  ADD COLUMN column_map JSONB,
  ADD COLUMN validation_result JSONB;
```

> **Note**: If `columns_detected`, `suggested_mapping`, and `confidence` are already stored (check the existing model), skip those columns. The key additions are `status`, `column_map`, and `validation_result`.

### Update Existing Handlers

| Handler | Changes |
|---|---|
| `POST /upload/` | Store `columns_detected`, `suggested_mapping`, `confidence`. Set `status = 'uploaded'`. |
| `POST /upload/validate` | Store `column_map`, `validation_result`. Set `status = 'validated'`. |
| `POST /upload/confirm` | Set `status = 'confirmed'`. |

---

## Frontend Integration

Once these endpoints exist, add to [FRONTEND_INTEGRATION.md](./FRONTEND_INTEGRATION.md):

```markdown
### Get Upload Session — `GET /api/v1/upload/{session_id}` 🔒

Returns session metadata (columns, suggested mapping, confidence). 
Use this to populate the column mapping step.

### Get Validation Result — `GET /api/v1/upload/{session_id}/validation` 🔒

Returns the stored validation result (product preview, quality report).
Use this to populate the review & confirm step.
Requires `POST /upload/validate` to have been called first.
```

### Frontend Changes

With these GET endpoints, the upload wizard becomes a set of independent routes:

```
/upload                → File drop step (POST /upload/)
/upload/mapping        → Column mapping (GET /upload/{id} via loader)
/upload/validation     → Review & confirm (GET /upload/{id}/validation via loader)
/upload/success        → Success (data from confirm response via nav state — one-time)
```

Each route (except success) has a **TanStack Router loader** that fetches its data from the GET endpoint. If the session is expired or missing, the loader redirects to `/upload`.

The `uploadSessionId` is passed between routes as a **search param** (`?session=uuid`), which gets stripped from the URL via `routeMasks` → user always sees `/upload`.

### TypeScript Types (no changes needed)

The existing `UploadSession` and `UploadValidation` types already match the GET response shapes. Just wire up new server functions:

```ts
// New server functions
export const getUploadSession = createServerFn({ method: 'GET' })
  .middleware([bearerAuth])
  .inputValidator(z.object({ sessionId: z.string().uuid() }))
  .handler(async ({ data, context }) => {
    return backendJson<ApiSuccess<UploadSession>>(
      `/upload/${data.sessionId}`,
      { authorization: context.authorization }
    )
  })

export const getUploadValidation = createServerFn({ method: 'GET' })
  .middleware([bearerAuth])
  .inputValidator(z.object({ sessionId: z.string().uuid() }))
  .handler(async ({ data, context }) => {
    return backendJson<ApiSuccess<UploadValidation>>(
      `/upload/${data.sessionId}/validation`,
      { authorization: context.authorization }
    )
  })
```
