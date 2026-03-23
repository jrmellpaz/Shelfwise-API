"""
Product endpoints — /api/v1/products/*

GET    /              — List all products (paginated, filterable)
GET    /{id}          — Get product details
PATCH  /{id}          — Update product metadata
PATCH  /{id}/archive  — Archive/unarchive a product
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.product import Product
from app.models.user import User
from app.core.exceptions import NotFoundException
from app.schemas.common import success_response, paginated_response

router = APIRouter()


@router.get("/")
async def list_products(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    is_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all products for the current user (paginated)."""
    query = db.query(Product).filter(
        Product.user_id == current_user.id,
        Product.is_archived == is_archived,
    )
    if category:
        query = query.filter(Product.category == category)

    total_items = query.count()
    products = query.offset((page - 1) * limit).limit(limit).all()

    return paginated_response(
        data=[
            {
                "id": str(p.id),
                "productId": p.product_id,
                "name": p.name,
                "category": p.category,
                "description": p.description,
                "isArchived": p.is_archived,
                "createdAt": p.created_at.isoformat() if p.created_at else None,
            }
            for p in products
        ],
        page=page,
        limit=limit,
        total_items=total_items,
    )


@router.get("/{product_uuid}")
async def get_product(
    product_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single product's details."""
    product = (
        db.query(Product)
        .filter(Product.id == product_uuid, Product.user_id == current_user.id)
        .first()
    )
    if not product:
        raise NotFoundException("Product")
    return success_response(data={
        "id": str(product.id),
        "productId": product.product_id,
        "name": product.name,
        "category": product.category,
        "description": product.description,
        "notes": product.notes,
        "isArchived": product.is_archived,
        "createdAt": product.created_at.isoformat() if product.created_at else None,
        "updatedAt": product.updated_at.isoformat() if product.updated_at else None,
    })


@router.patch("/{product_uuid}")
async def update_product(
    product_uuid: UUID,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update product metadata (category, description, notes)."""
    product = (
        db.query(Product)
        .filter(Product.id == product_uuid, Product.user_id == current_user.id)
        .first()
    )
    if not product:
        raise NotFoundException("Product")

    allowed_fields = {"category", "description", "notes"}
    for field, value in body.items():
        if field in allowed_fields:
            setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return success_response(data={"id": str(product.id)}, message="Product updated")


@router.patch("/{product_uuid}/archive")
async def toggle_archive(
    product_uuid: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archive or unarchive a product."""
    product = (
        db.query(Product)
        .filter(Product.id == product_uuid, Product.user_id == current_user.id)
        .first()
    )
    if not product:
        raise NotFoundException("Product")

    product.is_archived = not product.is_archived
    db.commit()
    db.refresh(product)
    status_text = "archived" if product.is_archived else "unarchived"
    return success_response(
        data={"id": str(product.id), "isArchived": product.is_archived},
        message=f"Product {status_text}",
    )
