"""
FastAPI auth dependencies: extract and validate the current user from the JWT.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.auth.jwt import decode_token
from civilengineer.db.models import UserModel
from civilengineer.db.session import get_session
from civilengineer.schemas.auth import User, UserRole

_bearer = HTTPBearer(auto_error=False)

_401 = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None:
        raise _401

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise _401

    result = await session.execute(
        select(UserModel).where(UserModel.user_id == payload.sub)
    )
    row = result.scalar_one_or_none()

    if row is None or not row.is_active:
        raise _401

    return User(
        user_id=row.user_id,
        firm_id=row.firm_id,
        email=row.email,
        full_name=row.full_name,
        role=UserRole(row.role),
        is_active=row.is_active,
        created_at=row.created_at,
        last_login=row.last_login,
    )


async def get_current_active_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    return user
