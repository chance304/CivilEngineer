"""
Admin router — LLM config and firm settings (firm_admin only).

GET    /api/v1/admin/llm-config        → get current LLM config (key masked)
PUT    /api/v1/admin/llm-config        → set LLM provider / model / key
POST   /api/v1/admin/llm-config/test   → test LLM connectivity
DELETE /api/v1/admin/llm-config        → remove firm config (revert to system default)
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.auth.password import decrypt_api_key, encrypt_api_key
from civilengineer.auth.rbac import Permission, require_permission
from civilengineer.core.config import get_settings
from civilengineer.db.models import FirmModel
from civilengineer.db.session import get_session
from civilengineer.schemas.auth import (
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMTestResult,
    User,
)

router = APIRouter(prefix="/admin", tags=["admin"])

settings = get_settings()


async def _get_firm_row(
    firm_id: str, session: AsyncSession
) -> FirmModel:
    result = await session.execute(
        select(FirmModel).where(FirmModel.firm_id == firm_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Firm record not found.")
    return row


def _settings_to_response(firm_settings: dict) -> LLMConfigResponse:
    llm = firm_settings.get("llm_config")
    if llm is None:
        return LLMConfigResponse(
            provider=settings.SYSTEM_LLM_PROVIDER,
            model=settings.SYSTEM_LLM_MODEL,
            api_key_last4=None,
            base_url=None,
            temperature=0.3,
            max_tokens=4096,
            using_system_default=True,
        )
    # Mask the API key — show only last 4 chars
    last4: str | None = None
    if llm.get("api_key_encrypted"):
        try:
            plaintext = decrypt_api_key(llm["api_key_encrypted"])
            last4 = plaintext[-4:] if len(plaintext) >= 4 else "****"
        except Exception:
            last4 = "****"

    return LLMConfigResponse(
        provider=llm.get("provider", "anthropic"),
        model=llm.get("model", "claude-sonnet-4-6"),
        api_key_last4=last4,
        base_url=llm.get("base_url"),
        temperature=llm.get("temperature", 0.3),
        max_tokens=llm.get("max_tokens", 4096),
        using_system_default=False,
    )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/llm-config", response_model=LLMConfigResponse)
async def get_llm_config(
    current_user: Annotated[User, Depends(require_permission(Permission.FIRM_SETTINGS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LLMConfigResponse:
    firm = await _get_firm_row(current_user.firm_id, session)
    return _settings_to_response(firm.settings or {})


@router.put("/llm-config", response_model=LLMConfigResponse)
async def set_llm_config(
    body: LLMConfigUpdate,
    current_user: Annotated[User, Depends(require_permission(Permission.FIRM_SETTINGS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LLMConfigResponse:
    firm = await _get_firm_row(current_user.firm_id, session)
    firm_settings = dict(firm.settings or {})
    existing_llm = firm_settings.get("llm_config", {})

    new_llm: dict = {
        "provider": body.provider,
        "model": body.model,
        "base_url": body.base_url,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
    }

    # If a new API key was provided, encrypt it
    if body.api_key:
        new_llm["api_key_encrypted"] = encrypt_api_key(body.api_key)
    else:
        # Keep existing key if none provided
        new_llm["api_key_encrypted"] = existing_llm.get("api_key_encrypted")

    firm_settings["llm_config"] = new_llm
    firm.settings = firm_settings
    session.add(firm)
    await session.flush()

    return _settings_to_response(firm_settings)


@router.post("/llm-config/test", response_model=LLMTestResult)
async def test_llm_config(
    current_user: Annotated[User, Depends(require_permission(Permission.FIRM_SETTINGS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LLMTestResult:
    """
    Test the firm's LLM configuration by sending a minimal completion request.
    """
    firm = await _get_firm_row(current_user.firm_id, session)
    llm_cfg = (firm.settings or {}).get("llm_config")

    if llm_cfg is None:
        # Test system default
        provider = settings.SYSTEM_LLM_PROVIDER
        model = settings.SYSTEM_LLM_MODEL
        api_key = settings.SYSTEM_LLM_API_KEY
        base_url = None
    else:
        provider = llm_cfg.get("provider", "anthropic")
        model = llm_cfg.get("model", "claude-sonnet-4-6")
        base_url = llm_cfg.get("base_url")
        enc_key = llm_cfg.get("api_key_encrypted")
        try:
            api_key = decrypt_api_key(enc_key) if enc_key else settings.SYSTEM_LLM_API_KEY
        except Exception:
            return LLMTestResult(success=False, error="Failed to decrypt API key.")

    try:
        import litellm  # type: ignore[import]

        kwargs: dict = {
            "model": f"{provider}/{model}" if provider not in ("anthropic", "openai") else model,
            "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
            "max_tokens": 10,
            "temperature": 0,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["api_base"] = base_url

        start = time.monotonic()
        await litellm.acompletion(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        return LLMTestResult(success=True, latency_ms=latency_ms)

    except Exception as exc:
        return LLMTestResult(success=False, error=str(exc))


@router.delete("/llm-config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_config(
    current_user: Annotated[User, Depends(require_permission(Permission.FIRM_SETTINGS))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Remove firm LLM config — reverts to system default."""
    firm = await _get_firm_row(current_user.firm_id, session)
    firm_settings = dict(firm.settings or {})
    firm_settings.pop("llm_config", None)
    firm.settings = firm_settings
    session.add(firm)
