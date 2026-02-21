"""
JWT token creation and verification.

Access token: 15-minute lifetime, returned in JSON body.
Refresh token: 7-day lifetime, set as httpOnly cookie. JTI stored in Redis
               to support server-side invalidation on logout.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from jose import jwt

from civilengineer.core.config import get_settings
from civilengineer.schemas.auth import TokenPayload, UserRole

settings = get_settings()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_access_token(
    user_id: str,
    firm_id: str,
    role: UserRole,
) -> str:
    now = _utc_now()
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "firm_id": firm_id,
        "role": role.value,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    user_id: str,
    firm_id: str,
    role: UserRole,
) -> tuple[str, str]:
    """
    Returns (token, jti).
    The caller must store jti in Redis with TTL = REFRESH_TOKEN_EXPIRE_DAYS.
    """
    jti = str(uuid.uuid4())
    now = _utc_now()
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "firm_id": firm_id,
        "role": role.value,
        "jti": jti,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def decode_token(token: str) -> TokenPayload:
    """
    Decode and validate a JWT. Raises JWTError on any failure.
    """
    payload = jwt.decode(
        token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    return TokenPayload(
        sub=payload["sub"],
        firm_id=payload["firm_id"],
        role=UserRole(payload["role"]),
        exp=payload["exp"],
        iat=payload["iat"],
        jti=payload.get("jti"),
    )


def refresh_token_expire_seconds() -> int:
    return settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
