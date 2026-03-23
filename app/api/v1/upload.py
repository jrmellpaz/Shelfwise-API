"""
Upload endpoints — /api/v1/upload/*

POST /           — Upload CSV, detect columns, return suggested mappings + uploadSessionId
POST /validate   — Apply column mapping, validate, return quality preview
POST /confirm    — Confirm upload and commit validated data to DB
GET  /template   — Download sample CSV template
"""

import io
import logging

import pandas as pd
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import FileTooLargeException, RowLimitExceededException, ValidationException
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

    session = upload_session_service.create_session(
        db, current_user.id, file.filename or "upload.csv", contents
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
            "rowCount": len(pd.read_csv(io.BytesIO(contents))),
            "fileName": file.filename,
            "fileSizeMb": round(size_mb, 2),
            **suggestions,
        },
        message=f"CSV uploaded — {len(csv_columns)} columns detected",
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
    if row.stage not in ("uploaded", "validated"):
        raise ValidationException("Invalid upload session state.")

    column_map = body.column_map
    if not column_map:
        raise ValidationException(
            "columnMap is required. Map your CSV columns to: date, product_id, quantity_sold (and optionally product_name)."
        )

    _validate_column_map_keys(column_map)

    df = csv_service.dataframe_from_column_mapping(row.raw_bytes, column_map)
    df, warnings = csv_service.validate_structure(df)

    quality_report = csv_service.assess_data_quality(df, warnings)
    data_health = csv_service.build_data_health_scorecard(df, quality_report, warnings)

    preview = csv_service.build_upload_preview(
        df, quality_report, data_health, current_user.id, db
    )

    upload_session_service.mark_validated(db, row, column_map)

    return success_response(
        data=json_safe(preview),
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
    if row.stage != "validated" or not row.column_map:
        raise ValidationException(
            "No validated upload found for this session. Please validate your CSV first."
        )

    df = csv_service.dataframe_from_column_mapping(row.raw_bytes, row.column_map)
    df, _warnings = csv_service.validate_structure(df)

    result = csv_service.commit_upload(
        df, current_user.id, db, skip_product_ids=body.skip_product_ids
    )

    upload_session_service.delete_session(db, row)

    return success_response(
        data=result,
        message=f"Upload committed — {result['totalRowsInserted']} rows inserted",
    )


# ── Template Download ─────────────────────────────────────────


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
