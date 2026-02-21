"""
Users router — user management for firm_admin.

GET  /api/v1/users/me        → current user profile
PATCH /api/v1/users/me       → update own profile / change password
GET  /api/v1/users/          → list all users in firm (firm_admin only)
POST /api/v1/users/          → create new user (firm_admin only)
PATCH /api/v1/users/{id}     → update user role / active status (firm_admin only)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.auth.dependencies import get_current_user
from civilengineer.auth.password import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from civilengineer.auth.rbac import Permission, require_permission
from civilengineer.db.models import UserModel
from civilengineer.db.session import get_session
from civilengineer.schemas.auth import (
    PasswordChange,
    User,
    UserCreate,
    UserRole,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


def _make_user_id() -> str:
    return f"usr_{uuid.uuid4().hex[:12]}"


def _row_to_user(row: UserModel) -> User:
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


# ------------------------------------------------------------------
# Current user
# ------------------------------------------------------------------

@router.get("/me", response_model=User)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    result = await session.execute(
        select(UserModel).where(UserModel.user_id == current_user.user_id)
    )
    row = result.scalar_one()

    if not verify_password(body.current_password, row.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    errors = validate_password_strength(body.new_password)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=errors,
        )

    row.hashed_password = hash_password(body.new_password)
    session.add(row)

    # Revoke all refresh tokens so re-login is required on all sessions
    from civilengineer.auth.redis_client import revoke_all_user_tokens
    await revoke_all_user_tokens(current_user.user_id)


# ------------------------------------------------------------------
# Admin: manage firm users
# ------------------------------------------------------------------

@router.get("/", response_model=list[User])
async def list_users(
    current_user: Annotated[User, Depends(require_permission(Permission.USER_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[User]:
    result = await session.execute(
        select(UserModel)
        .where(UserModel.firm_id == current_user.firm_id)
        .order_by(UserModel.created_at.desc())
    )
    rows = result.scalars().all()
    return [_row_to_user(r) for r in rows]


@router.post("/", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    current_user: Annotated[User, Depends(require_permission(Permission.USER_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    # Check email uniqueness
    existing = await session.execute(
        select(UserModel).where(UserModel.email == body.email)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    errors = validate_password_strength(body.password)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=errors,
        )

    row = UserModel(
        user_id=_make_user_id(),
        firm_id=current_user.firm_id,
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=body.role.value,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return _row_to_user(row)


@router.patch("/{user_id}", response_model=User)
async def update_user(
    user_id: str,
    body: UserUpdate,
    current_user: Annotated[User, Depends(require_permission(Permission.USER_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    result = await session.execute(
        select(UserModel).where(
            UserModel.user_id == user_id,
            UserModel.firm_id == current_user.firm_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if body.full_name is not None:
        row.full_name = body.full_name
    if body.role is not None:
        row.role = body.role.value
    if body.is_active is not None:
        row.is_active = body.is_active
        if not body.is_active:
            from civilengineer.auth.redis_client import revoke_all_user_tokens
            await revoke_all_user_tokens(user_id)

    session.add(row)
    await session.flush()
    return _row_to_user(row)
