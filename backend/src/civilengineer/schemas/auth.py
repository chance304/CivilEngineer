"""
Auth schemas: users, firms, JWT tokens, LLM config.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class UserRole(StrEnum):
    FIRM_ADMIN      = "firm_admin"       # Full firm access + user management
    SENIOR_ENGINEER = "senior_engineer"  # All projects, can approve designs
    ENGINEER        = "engineer"         # Own + assigned projects
    VIEWER          = "viewer"           # Read-only (clients, reviewers)


class LLMConfig(BaseModel):
    """
    LLM provider configuration set by firm_admin via the admin portal.
    API key stored encrypted in PostgreSQL — never exposed to the frontend.
    LiteLLM reads this at job-start time.
    """
    provider: str = "anthropic"
    # "anthropic" | "openai" | "azure" | "ollama" | "custom"
    model: str = "claude-sonnet-4-6"
    # Any model string LiteLLM accepts (e.g. "gpt-4o", "azure/gpt-4", "ollama/llama3")
    api_key_encrypted: str | None = None
    # Encrypted with system ENCRYPTION_KEY (Fernet). Never returned to frontend.
    base_url: str | None = None
    # Required for Azure OpenAI / Ollama / custom deployments
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, ge=256, le=65536)


class FirmSettings(BaseModel):
    """Firm-level configuration stored as JSONB in the firms table."""
    autocad_enabled: bool = False
    max_concurrent_jobs: int = 5
    custom_rules_enabled: bool = False
    default_cad_output: str = "dxf"     # "dxf" | "dwg"
    notification_email: str | None = None
    llm_config: LLMConfig | None = None
    # None → use system default from SYSTEM_LLM_* env vars


class Firm(BaseModel):
    """Civil engineering firm. All data is isolated per firm."""
    firm_id: str
    name: str
    country: str
    default_jurisdiction: str          # e.g. "NP-KTM", "IN", "US-CA"
    plan: str = "professional"
    settings: FirmSettings
    created_at: datetime


class User(BaseModel):
    """Engineer or staff member at a firm."""
    user_id: str
    firm_id: str
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool = True
    created_at: datetime
    last_login: datetime | None = None


class TokenPair(BaseModel):
    """Returned in JSON body on successful login."""
    access_token: str
    token_type: str = "bearer"
    # refresh_token is set as httpOnly cookie (not in this body)


class TokenPayload(BaseModel):
    """Claims decoded from a JWT."""
    sub: str          # user_id
    firm_id: str
    role: UserRole
    exp: int          # Unix timestamp
    iat: int
    jti: str | None = None   # Only present on refresh tokens


# ------------------------------------------------------------------
# Request / response bodies for auth endpoints
# ------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=8)
    role: UserRole = UserRole.ENGINEER


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class LLMConfigUpdate(BaseModel):
    """Request body for PUT /admin/llm-config."""
    provider: str
    model: str
    api_key: str | None = None   # plaintext from frontend — encrypted before saving
    base_url: str | None = None
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, ge=256, le=65536)


class LLMConfigResponse(BaseModel):
    """Response body for GET /admin/llm-config — api_key is masked."""
    provider: str
    model: str
    api_key_last4: str | None = None   # Last 4 chars of key if set
    base_url: str | None = None
    temperature: float
    max_tokens: int
    using_system_default: bool


class LLMTestResult(BaseModel):
    success: bool
    latency_ms: int | None = None
    error: str | None = None
