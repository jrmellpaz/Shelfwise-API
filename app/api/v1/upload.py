"""
Upload endpoints — /api/v1/upload/*

POST /                        — Upload CSV, detect columns, return suggested mappings + uploadSessionId
GET  /template                — Download sample CSV template
POST /validate                — Apply column mapping, validate, return quality preview
POST /confirm                 — Confirm upload and commit validated data to DB
GET  /{session_id}            — Re-fetch session metadata (columns, mapping, confidence)
GET  /{session_id}/validation — Re-fetch stored validation result
"""

import io
import logging
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import FileTooLargeException, NotFoundException, RowLimitExceededException, ValidationException
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.common import json_safe, success_response
from app.schemas.forecast import UploadConfirmRequest, UploadValidateRequest
from app.services import csv_service
from app.services import upload_session_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_column_map_keys(column_map: dict) -> None:
    required = ["date", "product_id", "quantity_sold"]
    missing = [f for f in required if not column_map.get(f)]
    if missing:
        raise ValidationException(
            f"Missing required column mappings: {missing}",
            details=[{"missingMappings": missing}],
        )


def _build_confidence_dict(suggestions: dict) -> dict:
    """Extract a flat {field: confidence} dict from suggest_column_mappings output."""
    mapping = suggestions.get("suggestedMapping", {})
    return {
        field: info.get("confidence")
        for field, info in mapping.items()
        if info.get("confidence") is not None
    }


# ── Step 1: Upload & Detect Columns ──────────────────────────


@router.post("/")
async def upload_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload CSV file and detect columns for mapping.

    Reads the CSV headers, runs auto-suggest fuzzy matching against
    the required fields, and returns column names + suggested mappings.
    Raw bytes are stored in csv_upload_sessions for validate/confirm.
    """
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)

    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise FileTooLargeException(settings.MAX_UPLOAD_SIZE_MB)

    df_peek = pd.read_csv(io.BytesIO(contents), nrows=5)

    if len(pd.read_csv(io.BytesIO(contents))) > settings.MAX_UPLOAD_ROWS:
        raise RowLimitExceededException(settings.MAX_UPLOAD_ROWS)

    csv_columns = list(df_peek.columns)
    suggestions = csv_service.suggest_column_mappings(csv_columns)
    confidence = _build_confidence_dict(suggestions)
    row_count = len(pd.read_csv(io.BytesIO(contents)))

    session = upload_session_service.create_session(
        db,
        current_user.id,
        file.filename or "upload.csv",
        contents,
        columns_detected=csv_columns,
        suggested_mapping=suggestions.get("suggestedMapping"),
        confidence=confidence,
    )

    logger.info(
        "CSV uploaded by user %s: %s (%.1f MB, %d columns), session=%s",
        current_user.id,
        file.filename,
        size_mb,
        len(csv_columns),
        session.id,
    )

    return success_response(
        data={
            "uploadSessionId": str(session.id),
            "columns": csv_columns,
            "rowCount": row_count,
            "fileName": file.filename,
            "fileSizeMb": round(size_mb, 2),
            "status": "uploaded",
            **suggestions,
        },
        message=f"CSV uploaded — {len(csv_columns)} columns detected",
    )


# ── Template Download ─────────────────────────────────────────
# NOTE: Must be defined BEFORE /{session_id} to avoid route conflict


@router.get("/template")
async def download_template():
    """Download a sample CSV template."""
    from fastapi.responses import StreamingResponse

    csv_content = (
        "date,product_id,product_name,quantity_sold\n"
        "2025-01-01,SKU-001,Widget A,42\n"
        "2025-01-02,SKU-001,Widget A,38\n"
        "2025-01-03,SKU-001,Widget A,45\n"
        "2025-01-01,SKU-002,Widget B,12\n"
        "2025-01-02,SKU-002,Widget B,15\n"
        "2025-01-03,SKU-002,Widget B,11\n"
    )
    buffer = io.BytesIO(csv_content.encode("utf-8"))
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales_template.csv"},
    )


# ── Step 2: Apply Mapping & Validate ─────────────────────────


@router.post("/validate")
async def validate_upload(
    body: UploadValidateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply column mapping, validate data, and return quality preview."""
    row = upload_session_service.get_session_for_user(
        db, body.upload_session_id, current_user.id
    )
    if row.status not in ("uploaded", "validated"):
        raise ValidationException("Invalid upload session state.")

    column_map = body.column_map
    if not column_map:
        raise ValidationException(
            "columnMap is required. Map your CSV columns to: date, product_id, quantity_sold (and optionally product_name)."
        )

    _validate_column_map_keys(column_map)

    # Semantic validation — catch wrong column types before processing
    semantic_warnings = csv_service.validate_column_semantics(
        row.raw_bytes, column_map
    )

    df = csv_service.dataframe_from_column_mapping(row.raw_bytes, column_map)
    original_row_count = len(df)
    df, warnings = csv_service.validate_structure(df)

    # Safety net: if cleaning dropped almost all rows, the mapping is likely wrong
    if original_row_count > 0 and len(df) == 0:
        raise ValidationException(
            "No rows survived validation. The column mapping is likely incorrect — "
            "check that each field is mapped to the correct CSV column.",
            details=[{"originalRows": original_row_count, "survivingRows": 0}],
        )
    if original_row_count > 10 and len(df) < original_row_count * 0.1:
        raise ValidationException(
            f"Only {len(df)} of {original_row_count} rows "
            f"({len(df) / original_row_count:.0%}) survived validation. "
            f"This usually indicates incorrect column mapping.",
            details=[{
                "originalRows": original_row_count,
                "survivingRows": len(df),
                "survivalRate": round(len(df) / original_row_count * 100, 1),
            }],
        )

    # Merge semantic warnings into the structural warnings list
    warnings = semantic_warnings + warnings

    quality_report = csv_service.assess_data_quality(df, warnings)
    data_health = csv_service.build_data_health_scorecard(df, quality_report, warnings)

    preview = csv_service.build_upload_preview(
        df, quality_report, data_health, current_user.id, db
    )

    safe_preview = json_safe(preview)

    upload_session_service.mark_validated(
        db, row, column_map, validation_result=safe_preview,
    )

    return success_response(
        data=safe_preview,
        message=f"CSV validated — {len(df)} rows across {quality_report['totalProducts']} products",
    )


# ── Step 3: Confirm & Commit ─────────────────────────────────


@router.post("/confirm")
async def confirm_upload(
    body: UploadConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm upload and commit validated data to DB.

    Optionally exclude specific products via skip_product_ids.
    """
    row = upload_session_service.get_session_for_user(
        db, body.upload_session_id, current_user.id
    )
    if row.status != "validated" or not row.column_map:
        raise ValidationException(
            "No validated upload found for this session. Please validate your CSV first."
        )

    df = csv_service.dataframe_from_column_mapping(row.raw_bytes, row.column_map)
    df, _warnings = csv_service.validate_structure(df)

    result = csv_service.commit_upload(
        df, current_user.id, db, skip_product_ids=body.skip_product_ids
    )

    # Mark confirmed before deleting so the status transitions are properly tracked
    upload_session_service.mark_confirmed(db, row)
    upload_session_service.delete_session(db, row)

    return success_response(
        data=result,
        message=f"Upload committed — {result['totalRowsInserted']} rows inserted",
    )


# ── GET Session Metadata ─────────────────────────────────────
# NOTE: Dynamic path routes must come AFTER static routes (/template, /validate, /confirm)


@router.get("/{session_id}")
async def get_upload_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return session metadata (columns, suggested mapping, confidence).

    Allows the frontend to re-fetch session data using only the
    uploadSessionId, enabling each wizard step to be self-contained.
    """
    row = upload_session_service.get_session_for_user(db, session_id, current_user.id)

    # Read row count from stored CSV bytes
    row_count = len(pd.read_csv(io.BytesIO(row.raw_bytes)))
    size_mb = len(row.raw_bytes) / (1024 * 1024)

    return success_response(
        data={
            "uploadSessionId": str(row.id),
            "columns": row.columns_detected or [],
            "rowCount": row_count,
            "fileName": row.filename,
            "fileSizeMb": round(size_mb, 2),
            "suggestedMapping": row.suggested_mapping or {},
            "confidence": row.confidence or {},
            "columnMap": row.column_map if row.status != "uploaded" else None,
            "status": row.status,
        },
    )


# ── GET Validation Result ────────────────────────────────────


@router.get("/{session_id}/validation")
async def get_validation_result(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the stored validation result for a session.

    Allows the frontend review/confirm step to re-fetch validation
    data using only the uploadSessionId.
    Requires POST /upload/validate to have been called first.
    """
    row = upload_session_service.get_session_for_user(db, session_id, current_user.id)

    if row.status == "uploaded" or row.validation_result is None:
        raise NotFoundException("Validation has not been run for this session")

    return success_response(
        data=row.validation_result,
    )
