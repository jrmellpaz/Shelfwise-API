"""
Authentication endpoints — /api/v1/auth/*

Public:  POST /register, POST /login, POST /refresh
Protected: POST /logout, GET /me
"""

import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AuthenticationException,
    DuplicateEmailException,
    InvalidCredentialsException,
    WeakPasswordException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.common import ApiResponse, success_response

router = APIRouter()

# Password strength: min 8 chars, at least 1 upper, 1 lower, 1 digit
PASSWORD_REGEX = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


@router.post("/register", response_model=ApiResponse[TokenResponse])
async def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account."""
    # Validate passwords match
    if body.password != body.password_confirm:
        raise WeakPasswordException("Passwords do not match")

    # Validate password strength
    if not PASSWORD_REGEX.match(body.password):
        raise WeakPasswordException(
            "Password must be at least 8 characters with 1 uppercase, "
            "1 lowercase, and 1 number"
        )

    # Check for duplicate email
    existing = db.query(User).filter(User.email == body.email.lower().strip()).first()
    if existing:
        raise DuplicateEmailException()

    # Create user
    user = User(
        email=body.email.lower().strip(),
        password_hash=hash_password(body.password),
        business_name=body.business_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Generate tokens
    tokens = TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=create_refresh_token(subject=str(user.id)),
    )
    return success_response(
        data=tokens.model_dump(by_alias=True),
        message="Account created successfully",
    )


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return token pair."""
    user = db.query(User).filter(User.email == body.email.lower().strip()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise InvalidCredentialsException()

    tokens = TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=create_refresh_token(subject=str(user.id)),
    )
    return success_response(data=tokens.model_dump(by_alias=True))


@router.post("/refresh", response_model=ApiResponse[TokenResponse])
async def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access token."""
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise AuthenticationException("Invalid token type")
        user_id = payload.get("sub")
    except Exception:
        raise AuthenticationException("Invalid or expired refresh token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AuthenticationException("User not found")

    tokens = TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=create_refresh_token(subject=str(user.id)),
    )
    return success_response(data=tokens.model_dump(by_alias=True))


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """Invalidate the current refresh token.

    Note: Full token invalidation requires a token blocklist (Redis or DB).
    For MVP, this endpoint acknowledges the logout on the client side.
    """
    return success_response(data=None, message="Logged out successfully")


@router.get("/me", response_model=ApiResponse[UserResponse])
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user info."""
    user_data = UserResponse.model_validate(current_user)
    return success_response(data=user_data.model_dump(by_alias=True))
