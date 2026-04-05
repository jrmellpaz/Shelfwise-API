"""
CSV Service — parsing, validation, quality assessment, and upload commit.

Migrated from pipeline_test.py Steps 1–3, adapted for FastAPI:
- Reads from UploadFile (in-memory bytes) instead of filesystem
- Raises AppException subclasses instead of sys.exit()
- Persists data via SQLAlchemy ORM instead of just returning DataFrames
"""

import io
import logging
import uuid
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import (
    FileTooLargeException,
    RowLimitExceededException,
    ValidationException,
)
from app.models.product import Product
from app.models.sales_data import SalesData

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["date", "product_id", "product_name", "quantity_sold"]

# Keyword patterns for auto-suggesting column mappings.
# Each required field has a list of (keywords, confidence) tuples.
# Checked in order; first match wins.
_MAPPING_HINTS: dict[str, list[tuple[list[str], str]]] = {
    "date": [
        (["date"], "high"),
        (["time"], "medium"),
        (["day"], "medium"),
        (["period"], "medium"),
    ],
    "product_id": [
        (["product_id"], "exact"),
        (["product", "id"], "high"),
        (["sku"], "high"),
        (["item_id"], "high"),
        (["item", "id"], "medium"),
    ],
    "product_name": [
        (["product_name"], "exact"),
        (["product", "name"], "high"),
        (["item_name"], "high"),
        (["item", "name"], "medium"),
        (["name"], "medium"),
        (["description"], "low"),
    ],
    "quantity_sold": [
        (["quantity_sold"], "exact"),
        (["quantity"], "high"),
        (["qty"], "high"),
        (["items_sold"], "high"),
        (["sold"], "medium"),
        (["units"], "medium"),
        (["volume"], "medium"),
        (["amount"], "low"),
    ],
}


def suggest_column_mappings(csv_columns: list[str]) -> dict:
    """Auto-suggest which CSV columns map to the required fields.

    Uses keyword overlap to score each CSV column against each required
    field.  Returns suggested mappings with confidence levels.
    """
    # Normalise CSV column names for matching
    normalised = {col: col.lower().strip().replace(" ", "_") for col in csv_columns}

    suggested: dict[str, dict] = {}
    used_csv_cols: set[str] = set()

    # Exact match pass first
    for req_field in REQUIRED_COLUMNS:
        for orig, norm in normalised.items():
            if norm == req_field and orig not in used_csv_cols:
                suggested[req_field] = {"csvColumn": orig, "confidence": "exact"}
                used_csv_cols.add(orig)
                break

    # Fuzzy match pass for remaining fields
    for req_field in REQUIRED_COLUMNS:
        if req_field in suggested:
            continue

        best_match: str | None = None
        best_confidence: str | None = None

        for orig, norm in normalised.items():
            if orig in used_csv_cols:
                continue

            for keywords, confidence in _MAPPING_HINTS.get(req_field, []):
                if all(kw in norm for kw in keywords):
                    best_match = orig
                    best_confidence = confidence
                    break
            if best_match:
                break

        if best_match:
            suggested[req_field] = {"csvColumn": best_match, "confidence": best_confidence}
            used_csv_cols.add(best_match)
        else:
            suggested[req_field] = {"csvColumn": None, "confidence": None}

    required_fields = ["date", "product_id", "quantity_sold"]
    optional_fields = ["product_name"]
    unmapped = [c for c in csv_columns if c not in used_csv_cols]

    return {
        "suggestedMapping": suggested,
        "unmappedCsvColumns": unmapped,
        "requiredFields": required_fields,
        "optionalFields": optional_fields,
    }


# ── Step 1: Parse CSV ─────────────────────────────────────────


async def parse_csv(
    file: UploadFile,
    column_map: dict | None = None,
) -> pd.DataFrame:
    """Parse an UploadFile into a DataFrame.

    Enforces file-size and row-count limits from settings.
    Optionally remaps column names via *column_map*.
    """
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)

    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise FileTooLargeException(settings.MAX_UPLOAD_SIZE_MB)

    df = pd.read_csv(io.BytesIO(contents))

    # Apply column mapping if provided
    if column_map:
        rename_dict = {
            column_map["date"]: "date",
            column_map["product_id"]: "product_id",
            column_map["quantity_sold"]: "quantity_sold",
        }
        mapped_name_col = column_map.get("product_name")
        if mapped_name_col in df.columns:
            rename_dict[mapped_name_col] = "product_name"
        df = df.rename(columns=rename_dict)

    # Fallback: duplicate product_id → product_name if missing
    if "product_name" not in df.columns and "product_id" in df.columns:
        logger.warning("'product_name' column missing — using 'product_id' as fallback")
        df["product_name"] = df["product_id"].astype(str)

    if len(df) > settings.MAX_UPLOAD_ROWS:
        raise RowLimitExceededException(settings.MAX_UPLOAD_ROWS)

    logger.info("Loaded %d rows from %s (%.1f MB)", len(df), file.filename, size_mb)
    return df


def dataframe_from_column_mapping(raw_bytes: bytes, column_map: dict) -> pd.DataFrame:
    """Parse CSV bytes and apply column_map renames (before validate_structure)."""
    df = pd.read_csv(io.BytesIO(raw_bytes))
    rename_dict = {}
    for target_field, csv_col in column_map.items():
        if csv_col and csv_col in df.columns:
            rename_dict[csv_col] = target_field
    df = df.rename(columns=rename_dict)
    if "product_name" not in df.columns and "product_id" in df.columns:
        logger.warning("'product_name' not mapped — using 'product_id' as fallback")
        df["product_name"] = df["product_id"].astype(str)
    return df


# ── Step 1b: Semantic Column Validation ───────────────────────


def validate_column_semantics(raw_bytes: bytes, column_map: dict) -> list[str]:
    """Check that mapped columns contain data matching their expected types.

    Runs BEFORE column renaming to catch obviously wrong mappings early.
    Raises ValidationException for clearly invalid mappings.
    Returns a list of warning strings for borderline cases.
    """
    df = pd.read_csv(io.BytesIO(raw_bytes))
    semantic_warnings: list[str] = []
    fatal_issues: list[dict] = []
    total_rows = len(df)

    if total_rows == 0:
        raise ValidationException("CSV file contains no data rows")

    # ── Date field: must be parseable as real dates ──────────
    date_csv_col = column_map.get("date")
    if date_csv_col and date_csv_col in df.columns:
        raw = df[date_csv_col].dropna()
        if len(raw) > 0:
            parsed = pd.to_datetime(raw, errors="coerce")
            parseable_count = int(parsed.notna().sum())
            parse_rate = parseable_count / len(raw)

            if parse_rate < 0.5:
                # Majority of values are not recognisable as dates
                sample = [str(v) for v in raw.head(5).tolist()]
                fatal_issues.append({
                    "field": "date",
                    "mappedColumn": date_csv_col,
                    "issue": (
                        f"Only {parse_rate:.0%} of values in '{date_csv_col}' "
                        f"are recognizable as dates. "
                        f"This column likely does not contain date values."
                    ),
                    "sampleValues": sample,
                    "parseableCount": parseable_count,
                    "totalCount": len(raw),
                })
            else:
                # Dates parsed — check range is reasonable (catch epoch
                # timestamps from numeric columns, e.g. pd.to_datetime(42)
                # → 1970-01-01)
                valid_dates = parsed.dropna()
                if len(valid_dates) > 0:
                    min_date = valid_dates.min()
                    max_date = valid_dates.max()
                    if min_date < pd.Timestamp("1990-01-01"):
                        fatal_issues.append({
                            "field": "date",
                            "mappedColumn": date_csv_col,
                            "issue": (
                                f"Earliest parsed date from '{date_csv_col}' is "
                                f"{min_date.strftime('%Y-%m-%d')}, which is before 1990. "
                                f"This column may contain numeric values that were "
                                f"misinterpreted as dates."
                            ),
                            "sampleValues": [str(v) for v in raw.head(5).tolist()],
                            "parsedDateRange": (
                                f"{min_date.strftime('%Y-%m-%d')} to "
                                f"{max_date.strftime('%Y-%m-%d')}"
                            ),
                        })

                # Warn if a notable chunk of dates didn't parse
                if 0.5 <= parse_rate < 0.9:
                    unparseable_pct = (1 - parse_rate) * 100
                    semantic_warnings.append(
                        f"{unparseable_pct:.0f}% of values in '{date_csv_col}' "
                        f"are not parseable as dates — those rows will be dropped"
                    )

    # ── Quantity field: must be numeric ──────────────────────
    qty_csv_col = column_map.get("quantity_sold")
    if qty_csv_col and qty_csv_col in df.columns:
        raw = df[qty_csv_col].dropna()
        if len(raw) > 0:
            numeric = pd.to_numeric(raw, errors="coerce")
            numeric_count = int(numeric.notna().sum())
            numeric_rate = numeric_count / len(raw)

            if numeric_rate < 0.5:
                sample = [str(v) for v in raw.head(5).tolist()]
                fatal_issues.append({
                    "field": "quantity_sold",
                    "mappedColumn": qty_csv_col,
                    "issue": (
                        f"Only {numeric_rate:.0%} of values in '{qty_csv_col}' "
                        f"are numeric. This column likely does not contain "
                        f"quantity or sales data."
                    ),
                    "sampleValues": sample,
                    "numericCount": numeric_count,
                    "totalCount": len(raw),
                })
            elif numeric_rate < 0.9:
                non_numeric_pct = (1 - numeric_rate) * 100
                semantic_warnings.append(
                    f"{non_numeric_pct:.0f}% of values in '{qty_csv_col}' "
                    f"are not numeric — those will be set to 0"
                )

    # ── Product ID: warn if suspiciously high uniqueness ─────
    pid_csv_col = column_map.get("product_id")
    if pid_csv_col and pid_csv_col in df.columns and total_rows > 20:
        n_unique = df[pid_csv_col].nunique()
        uniqueness = n_unique / total_rows
        if uniqueness > 0.9:
            semantic_warnings.append(
                f"'{pid_csv_col}' has {n_unique} unique values across "
                f"{total_rows} rows ({uniqueness:.0%} unique) — "
                f"this may not be a product identifier column"
            )

    if fatal_issues:
        raise ValidationException(
            "Column mapping appears incorrect — the mapped columns do not "
            "contain the expected data types.",
            details=fatal_issues,
        )

    return semantic_warnings


# ── Step 2: Validate Structure ────────────────────────────────


def validate_structure(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Validate CSV structure and clean recoverable issues.

    Returns (cleaned DataFrame, list of warning messages).
    Raises ValidationException for fatal problems.
    """
    warnings_list: list[str] = []
    df = df.copy()

    # Check required columns
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValidationException(
            f"Missing required columns: {missing_cols}",
            details=[{"missing": missing_cols, "found": list(df.columns)}],
        )

    # Warn about extra columns
    extra_cols = [c for c in df.columns if c not in REQUIRED_COLUMNS]
    if extra_cols:
        warnings_list.append(f"Extra columns ignored: {extra_cols}")

    # Handle empty strings / whitespace → NaN
    for col in REQUIRED_COLUMNS:
        if df[col].dtype == object:
            mask = df[col].astype(str).str.strip().isin(["", "nan", "null", "None"])
            n_empty = mask.sum()
            if n_empty > 0:
                df.loc[mask, col] = np.nan
                warnings_list.append(
                    f"{n_empty} empty/whitespace values in '{col}' → treated as NaN"
                )

    # Handle null dates
    null_dates = df["date"].isna().sum()
    if null_dates > 0:
        warnings_list.append(f"{null_dates} null date values → rows dropped")
        df = df.dropna(subset=["date"])

    # Handle unparseable dates
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    unparseable = df["date"].isna().sum()
    if unparseable > 0:
        warnings_list.append(f"{unparseable} unparseable date values → rows dropped")
        df = df.dropna(subset=["date"])

    # Handle future dates
    today = pd.Timestamp.now().normalize()
    future_mask = df["date"] > today
    n_future = future_mask.sum()
    if n_future > 0:
        warnings_list.append(f"{n_future} future-dated rows → dropped")
        df = df[~future_mask]

    # Handle type mismatches in quantity_sold
    df["quantity_sold"] = pd.to_numeric(df["quantity_sold"], errors="coerce")
    n_coerced = df["quantity_sold"].isna().sum()
    if n_coerced > 0:
        warnings_list.append(
            f"{n_coerced} non-numeric values in quantity_sold → rows dropped"
        )
        df = df.dropna(subset=["quantity_sold"])

    # Drop rows with quantity_sold <= 0 (DB constraint requires > 0)
    non_positive = (df["quantity_sold"] <= 0).sum()
    if non_positive > 0:
        warnings_list.append(
            f"{non_positive} non-positive values in quantity_sold → rows dropped"
        )
        df = df[df["quantity_sold"] > 0]

    df = df.reset_index(drop=True)
    logger.info("Validation complete: %d clean rows", len(df))
    return df, warnings_list


# ── Step 3: Data Quality Assessment ───────────────────────────


def assess_data_quality(
    df: pd.DataFrame,
    validation_warnings: list[str] | None = None,
) -> dict:
    """Generate a comprehensive data quality report."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    products = df["product_id"].unique()
    date_min = df["date"].min()
    date_max = df["date"].max()
    date_range_days = (date_max - date_min).days

    # Detect duplicates
    duplicates = df.duplicated(subset=["date", "product_id"], keep=False)
    num_duplicates = int(duplicates.sum())

    # Missing values
    missing_values = {k: int(v) for k, v in df.isnull().sum().items()}

    # Zero-sales products
    zero_sales_products: list[str] = []

    # Per-product stats
    product_stats: dict[str, dict] = {}
    for pid in sorted(products):
        pdf = df[df["product_id"] == pid]
        p_dates = pdf["date"].nunique()
        expected_dates = (pdf["date"].max() - pdf["date"].min()).days + 1
        completeness = (p_dates / expected_dates * 100) if expected_dates > 0 else 0
        months_of_data = (pdf["date"].max() - pdf["date"].min()).days / 30.44
        avg_sales = round(float(pdf["quantity_sold"].mean()), 1)
        is_zero_sales = avg_sales == 0 or pdf["quantity_sold"].sum() == 0

        if is_zero_sales:
            zero_sales_products.append(str(pid))

        product_stats[str(pid)] = {
            "name": str(pdf["product_name"].iloc[0]),
            "rows": len(pdf),
            "uniqueDates": p_dates,
            "expectedDates": expected_dates,
            "completenessPct": round(completeness, 1),
            "monthsOfData": round(months_of_data, 1),
            "hasSufficientData": months_of_data >= 6,
            "avgDailySales": avg_sales,
            "isZeroSales": is_zero_sales,
        }

    report = {
        "totalRows": len(df),
        "totalProducts": len(products),
        "dateRange": f"{date_min.strftime('%Y-%m-%d')} → {date_max.strftime('%Y-%m-%d')}",
        "dateRangeDays": date_range_days,
        "duplicatesFound": num_duplicates,
        "missingValues": missing_values,
        "zeroSalesProducts": zero_sales_products,
        "validationWarnings": validation_warnings or [],
        "productStats": product_stats,
    }
    return report


def build_data_health_scorecard(
    df: pd.DataFrame,
    quality_report: dict,
    validation_warnings: list[str],
) -> dict:
    """Build a structured data health scorecard (0–100 scale)."""
    product_stats = quality_report.get("productStats", {})

    # ── Completeness (30%) ──
    if product_stats:
        avg_completeness = sum(
            s["completenessPct"] for s in product_stats.values()
        ) / len(product_stats)
    else:
        avg_completeness = 0
    completeness_score = min(100, round(avg_completeness))
    total_expected = sum(s.get("expectedDates", 0) for s in product_stats.values())
    total_actual = sum(s.get("uniqueDates", 0) for s in product_stats.values())
    missing_dates = total_expected - total_actual
    completeness_detail = (
        f"{missing_dates} missing date entries across {len(product_stats)} products"
    )

    # ── Consistency (25%) ──
    n_issues = len(validation_warnings)
    consistency_score = max(0, 100 - (n_issues * 10))
    consistency_detail = (
        f"{n_issues} issues cleaned during validation"
        if n_issues > 0
        else "No data quality issues found"
    )

    # ── Freshness (20%) ──
    df_copy = df.copy()
    df_copy["date"] = pd.to_datetime(df_copy["date"])
    most_recent = df_copy["date"].max()
    days_since_latest = (pd.Timestamp.now() - most_recent).days
    if days_since_latest <= 1:
        freshness_score = 100
    elif days_since_latest <= 7:
        freshness_score = 90
    elif days_since_latest <= 30:
        freshness_score = 70
    elif days_since_latest <= 90:
        freshness_score = 50
    else:
        freshness_score = max(0, 30 - (days_since_latest - 90) // 30 * 10)
    freshness_detail = (
        f"Most recent data: {most_recent.strftime('%Y-%m-%d')} "
        f"({days_since_latest} days ago)"
    )

    # ── Volume (25%) ──
    if product_stats:
        avg_months = sum(
            s["monthsOfData"] for s in product_stats.values()
        ) / len(product_stats)
    else:
        avg_months = 0
    if avg_months >= 24:
        volume_score = 100
    elif avg_months >= 12:
        volume_score = 80
    elif avg_months >= 6:
        volume_score = 60
    elif avg_months >= 3:
        volume_score = 40
    else:
        volume_score = 20
    volume_detail = f"{avg_months:.1f} months average history (recommended: 12+)"

    # ── Overall ──
    overall = round(
        completeness_score * 0.30
        + consistency_score * 0.25
        + freshness_score * 0.20
        + volume_score * 0.25
    )
    if overall >= 90:
        rating = "Excellent"
    elif overall >= 70:
        rating = "Good"
    elif overall >= 50:
        rating = "Fair"
    else:
        rating = "Poor"

    return {
        "overallScore": overall,
        "rating": rating,
        "categories": {
            "completeness": {"score": completeness_score, "details": completeness_detail},
            "consistency": {"score": consistency_score, "details": consistency_detail},
            "freshness": {"score": freshness_score, "details": freshness_detail},
            "volume": {"score": volume_score, "details": volume_detail},
        },
        "issuesFixed": validation_warnings,
        "warnings": [
            f"{pid} has only {s['monthsOfData']}mo of data"
            for pid, s in product_stats.items()
            if not s["hasSufficientData"]
        ]
        + [
            f"{pid} has zero sales"
            for pid, s in product_stats.items()
            if s["isZeroSales"]
        ],
    }


# ── Upload Preview & Commit ───────────────────────────────────


def build_upload_preview(
    df: pd.DataFrame,
    quality_report: dict,
    data_health: dict,
    user_id,
    db: Session,
) -> dict:
    """Compare new CSV data against existing DB data.

    Returns an upload summary with per-product row counts and
    suspicious-replacement flags per BACKEND_REFERENCE FR-02.
    """
    df["product_id"] = df["product_id"].astype(str)
    product_ids = sorted(df["product_id"].unique())

    products_summary: list[dict] = []
    has_suspicious = False

    for pid in product_ids:
        new_count = int(len(df[df["product_id"] == pid]))
        pname = str(df[df["product_id"] == pid]["product_name"].iloc[0])

        # Look up existing product
        existing_product = (
            db.query(Product)
            .filter(Product.user_id == user_id, Product.product_id == pid)
            .first()
        )

        old_count = 0
        if existing_product:
            old_count = (
                db.query(SalesData)
                .filter(SalesData.product_id == existing_product.id)
                .count()
            )

        suspicious = old_count > 0 and new_count < old_count * 0.5
        if suspicious:
            has_suspicious = True

        products_summary.append({
            "productId": pid,
            "productName": pname,
            "existingRows": old_count,
            "newRows": new_count,
            "isNew": old_count == 0,
            "isSuspicious": suspicious,
            "action": "add" if old_count == 0 else "replace",
        })

    return {
        "products": products_summary,
        "hasSuspicious": has_suspicious,
        "qualityReport": quality_report,
        "dataHealth": data_health,
    }


def commit_upload(
    df: pd.DataFrame,
    user_id,
    db: Session,
    skip_product_ids: list[str] | None = None,
) -> dict:
    """Delete old sales_data for replaced products, insert new rows.

    Creates Product records for new products.
    Returns summary of what was committed.
    """
    df = df.copy()
    df["product_id"] = df["product_id"].astype(str)
    df["date"] = pd.to_datetime(df["date"])

    skip_set = set(skip_product_ids or [])
    upload_id = uuid.uuid4()
    product_ids = sorted(df["product_id"].unique())

    created_products = 0
    replaced_products = 0
    total_rows_inserted = 0

    for pid in product_ids:
        if pid in skip_set:
            continue

        pdf = df[df["product_id"] == pid]
        pname = str(pdf["product_name"].iloc[0])

        # Find or create Product
        product = (
            db.query(Product)
            .filter(Product.user_id == user_id, Product.product_id == pid)
            .first()
        )
        if product:
            # Delete old sales data for this product
            db.query(SalesData).filter(
                SalesData.product_id == product.id
            ).delete(synchronize_session=False)
            replaced_products += 1
        else:
            product = Product(
                user_id=user_id,
                product_id=pid,
                name=pname,
            )
            db.add(product)
            db.flush()  # Generate the product.id
            created_products += 1

        # Insert new sales data rows
        rows = []
        for _, row in pdf.iterrows():
            rows.append(
                SalesData(
                    user_id=user_id,
                    product_id=product.id,
                    date=row["date"].date(),
                    quantity_sold=float(row["quantity_sold"]),
                    upload_id=upload_id,
                )
            )
        db.add_all(rows)
        total_rows_inserted += len(rows)

    db.commit()

    logger.info(
        "Upload committed: %d products created, %d replaced, %d rows inserted",
        created_products,
        replaced_products,
        total_rows_inserted,
    )

    return {
        "uploadId": str(upload_id),
        "productsCreated": created_products,
        "productsReplaced": replaced_products,
        "totalRowsInserted": total_rows_inserted,
    }
