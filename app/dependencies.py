"""
Shared FastAPI dependencies.

- get_current_user: extracts and validates the JWT token from the
  Authorization header, returns the authenticated User ORM object.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AuthenticationException, TokenExpiredException
from app.core.security import decode_token
from app.database import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate the current user from the JWT access token.

    Used as a dependency in all protected route handlers.
    """
    try:
        payload = decode_token(token)
        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")

        if user_id is None:
            raise AuthenticationException("Invalid token payload")
        if token_type != "access":
            raise AuthenticationException("Invalid token type")

    except JWTError:
        raise AuthenticationException("Could not validate credentials")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AuthenticationException("User not found")

    return user
