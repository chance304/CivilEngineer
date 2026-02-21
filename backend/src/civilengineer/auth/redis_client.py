"""
Redis client for refresh token storage and invalidation.

Refresh tokens are stored as:
    Key:   "refresh:{jti}"
    Value: "{user_id}"
    TTL:   REFRESH_TOKEN_EXPIRE_DAYS * 86400 seconds

On logout: delete the key.
On refresh: check key exists before issuing new access token.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from civilengineer.core.config import get_settings

settings = get_settings()

_pool: aioredis.ConnectionPool | None = None


def _get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            db=settings.REDIS_REFRESH_TOKEN_DB,
            decode_responses=True,
            max_connections=20,
        )
    return _pool


def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=_get_pool())


async def store_refresh_token(jti: str, user_id: str, ttl_seconds: int) -> None:
    async with get_redis() as r:
        await r.setex(f"refresh:{jti}", ttl_seconds, user_id)


async def is_refresh_token_valid(jti: str) -> bool:
    async with get_redis() as r:
        return await r.exists(f"refresh:{jti}") == 1


async def revoke_refresh_token(jti: str) -> None:
    async with get_redis() as r:
        await r.delete(f"refresh:{jti}")


async def revoke_all_user_tokens(user_id: str) -> None:
    """
    Revoke all refresh tokens for a user (on password change or deactivation).
    Uses SCAN to find all matching keys — safe on large Redis instances.
    """
    async with get_redis() as r:
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match="refresh:*", count=100)
            for key in keys:
                val = await r.get(key)
                if val == user_id:
                    await r.delete(key)
            if cursor == 0:
                break
