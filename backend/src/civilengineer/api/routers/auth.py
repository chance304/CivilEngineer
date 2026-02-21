"""
Authentication router.

POST /api/v1/auth/login     → JWT access token + refresh cookie
POST /api/v1/auth/refresh   → new access token (reads refresh cookie)
DELETE /api/v1/auth/logout  → invalidate refresh token
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.auth.dependencies import get_current_user
from civilengineer.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    refresh_token_expire_seconds,
)
from civilengineer.auth.password import verify_password
from civilengineer.auth.redis_client import (
    is_refresh_token_valid,
    revoke_refresh_token,
    store_refresh_token,
)
from civilengineer.db.models import UserModel
from civilengineer.db.session import get_session
from civilengineer.schemas.auth import LoginRequest, TokenPair, User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    result = await session.execute(
        select(UserModel).where(UserModel.email == body.email)
    )
    user_row = result.scalar_one_or_none()

    if user_row is None or not verify_password(body.password, user_row.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user_row.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    role = UserRole(user_row.role)
    access_token = create_access_token(user_row.user_id, user_row.firm_id, role)
    refresh_token, jti = create_refresh_token(user_row.user_id, user_row.firm_id, role)
    ttl = refresh_token_expire_seconds()

    await store_refresh_token(jti, user_row.user_id, ttl)

    # Update last_login timestamp
    user_row.last_login = datetime.now(UTC)
    session.add(user_row)

    # Set refresh token as httpOnly cookie
    response.set_cookie(
        key=_COOKIE_NAME,
        value=refresh_token,
        max_age=ttl,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api/v1/auth",
    )

    return TokenPair(access_token=access_token)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh_token: Annotated[str | None, Cookie(alias=_COOKIE_NAME)] = None,
) -> TokenPair:
    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
    )
    if refresh_token is None:
        raise _invalid

    try:
        payload = decode_token(refresh_token)
    except JWTError:
        raise _invalid

    if payload.jti is None:
        raise _invalid
    if not await is_refresh_token_valid(payload.jti):
        raise _invalid

    # Revoke the old refresh token (token rotation)
    await revoke_refresh_token(payload.jti)

    # Re-query user to get latest role / active status
    result = await session.execute(
        select(UserModel).where(UserModel.user_id == payload.sub)
    )
    user_row = result.scalar_one_or_none()
    if user_row is None or not user_row.is_active:
        raise _invalid

    role = UserRole(user_row.role)
    new_access = create_access_token(user_row.user_id, user_row.firm_id, role)
    new_refresh, new_jti = create_refresh_token(user_row.user_id, user_row.firm_id, role)
    ttl = refresh_token_expire_seconds()
    await store_refresh_token(new_jti, user_row.user_id, ttl)

    response.set_cookie(
        key=_COOKIE_NAME,
        value=new_refresh,
        max_age=ttl,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api/v1/auth",
    )

    return TokenPair(access_token=new_access)


@router.delete("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    refresh_token: Annotated[str | None, Cookie(alias=_COOKIE_NAME)] = None,
) -> None:
    if refresh_token is not None:
        try:
            payload = decode_token(refresh_token)
            if payload.jti:
                await revoke_refresh_token(payload.jti)
        except JWTError:
            pass  # Token already invalid — ignore

    response.delete_cookie(key=_COOKIE_NAME, path="/api/v1/auth")
