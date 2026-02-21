"""
Role-Based Access Control (RBAC).

Defines permissions and maps them to roles. Also provides the
`require_permission` FastAPI dependency factory.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from fastapi import Depends, HTTPException, status

from civilengineer.schemas.auth import User, UserRole


class Permission(StrEnum):
    # Project
    PROJECT_CREATE  = "project:create"
    PROJECT_READ    = "project:read"
    PROJECT_UPDATE  = "project:update"
    PROJECT_DELETE  = "project:delete"
    # Design
    DESIGN_SUBMIT   = "design:submit"
    DESIGN_APPROVE  = "design:approve"
    DESIGN_READ     = "design:read"
    DESIGN_DOWNLOAD = "design:download"
    # Admin
    USER_MANAGE     = "user:manage"
    FIRM_SETTINGS   = "firm:settings"
    RULES_OVERRIDE  = "rules:override"
    BUILDING_CODES  = "building_codes:manage"


_ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.FIRM_ADMIN: _ALL_PERMISSIONS,
    UserRole.SENIOR_ENGINEER: frozenset({
        Permission.PROJECT_CREATE,
        Permission.PROJECT_READ,
        Permission.PROJECT_UPDATE,
        Permission.DESIGN_SUBMIT,
        Permission.DESIGN_APPROVE,
        Permission.DESIGN_READ,
        Permission.DESIGN_DOWNLOAD,
    }),
    UserRole.ENGINEER: frozenset({
        Permission.PROJECT_CREATE,
        Permission.PROJECT_READ,
        Permission.PROJECT_UPDATE,
        Permission.DESIGN_SUBMIT,
        Permission.DESIGN_APPROVE,
        Permission.DESIGN_READ,
        Permission.DESIGN_DOWNLOAD,
    }),
    UserRole.VIEWER: frozenset({
        Permission.PROJECT_READ,
        Permission.DESIGN_READ,
        Permission.DESIGN_DOWNLOAD,
    }),
}


def has_permission(user: User, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.role, frozenset())


def require_permission(permission: Permission) -> Callable:
    """FastAPI dependency factory: 403 if user lacks the permission."""
    from civilengineer.auth.dependencies import get_current_user

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission.value}",
            )
        return current_user

    return _check


def require_roles(*roles: UserRole) -> Callable:
    """FastAPI dependency factory: 403 if user's role is not in `roles`."""
    from civilengineer.auth.dependencies import get_current_user

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role.",
            )
        return current_user

    return _check
