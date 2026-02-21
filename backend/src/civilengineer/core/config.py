"""
Application settings loaded from environment variables.

In development: create backend/.env (copy .env.example and fill in values).
In production: set environment variables via Docker / Kubernetes secrets.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME: str = "CivilEngineer API"
    APP_VERSION: str = "0.2.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"   # "development" | "staging" | "production"

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://civilengineer:civilengineer@localhost:5432/civilengineer"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Sync URL used only by Alembic migrations
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://civilengineer:civilengineer@localhost:5432/civilengineer"

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_REFRESH_TOKEN_DB: int = 1   # Separate DB for refresh tokens

    # ------------------------------------------------------------------
    # JWT
    # ------------------------------------------------------------------
    SECRET_KEY: str = "change-me-in-production-use-a-64-char-random-string"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ------------------------------------------------------------------
    # Encryption (for LLM API keys stored in DB)
    # ------------------------------------------------------------------
    ENCRYPTION_KEY: str = "change-me-32-bytes-base64-encoded-key="
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    # ------------------------------------------------------------------
    # Storage (S3 / MinIO)
    # ------------------------------------------------------------------
    S3_ENDPOINT_URL: str | None = "http://localhost:9000"  # None for AWS
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_PROJECTS: str = "civilengineer-projects"
    S3_BUCKET_BUILDING_CODES: str = "civilengineer-codes"
    S3_REGION: str = "us-east-1"

    # ------------------------------------------------------------------
    # Default system LLM (fallback when firm has no LLM config)
    # ------------------------------------------------------------------
    SYSTEM_LLM_PROVIDER: str = "anthropic"
    SYSTEM_LLM_MODEL: str = "claude-sonnet-4-6"
    SYSTEM_LLM_API_KEY: str | None = None

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
