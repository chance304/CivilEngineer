"""
Admin router — LLM config, firm settings, and building code management (firm_admin only).

LLM config:
  GET    /api/v1/admin/llm-config              → current LLM config (key masked)
  PUT    /api/v1/admin/llm-config              → set LLM provider / model / key
  POST   /api/v1/admin/llm-config/test         → test LLM connectivity
  DELETE /api/v1/admin/llm-config              → revert to system default

Building codes (PDF → rules workflow):
  POST   /api/v1/admin/building-codes/upload           → upload PDF → S3 → DB record
  GET    /api/v1/admin/building-codes                  → list documents for firm
  GET    /api/v1/admin/building-codes/{doc_id}/rules   → list extracted rules (review queue)
  PUT    /api/v1/admin/building-codes/{doc_id}/rules/{rule_id}  → approve / reject rule
  POST   /api/v1/admin/building-codes/{doc_id}/activate         → promote approved rules → DB
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.auth.password import decrypt_api_key, encrypt_api_key
from civilengineer.auth.rbac import Permission, require_permission
from civilengineer.core.config import get_settings
from civilengineer.db.models import BuildingCodeDocumentModel, FirmModel
from civilengineer.db.repositories import rule_repository
from civilengineer.db.session import get_session
from civilengineer.schemas.auth import (
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMTestResult,
    User,
)
from civilengineer.schemas.building_codes import (
    ActivateRulesResponse,
    BuildingCodeDocumentResponse,
    ExtractionJobStarted,
    ExtractedRuleResponse,
    RuleReviewRequest,
)
from civilengineer.storage import s3_backend

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


# ===========================================================================
# Building code PDF upload and rule review endpoints
# ===========================================================================

_BUCKET = "building-codes"
_ALLOWED_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}


def _extracted_rule_to_response(r: object) -> ExtractedRuleResponse:
    return ExtractedRuleResponse(
        extracted_rule_id=r.extracted_rule_id,
        doc_id=r.doc_id,
        jurisdiction=r.jurisdiction,
        proposed_rule_id=r.proposed_rule_id,
        name=r.name,
        description=r.description,
        source_section=r.source_section,
        source_page=r.source_page,
        source_text=r.source_text,
        category=r.category,
        severity=r.severity,
        numeric_value=r.numeric_value,
        unit=r.unit,
        confidence=r.confidence,
        reviewer_approved=r.reviewer_approved,
        reviewer_notes=r.reviewer_notes,
        reviewed_by=r.reviewed_by,
        reviewed_at=r.reviewed_at,
        verification_status=getattr(r, "verification_status", "pending"),
        verification_notes=getattr(r, "verification_notes", ""),
        verification_confidence=getattr(r, "verification_confidence", None),
    )


def _doc_to_response(doc: BuildingCodeDocumentModel) -> BuildingCodeDocumentResponse:
    return BuildingCodeDocumentResponse(
        doc_id=doc.doc_id,
        firm_id=doc.firm_id,
        jurisdiction=doc.jurisdiction,
        code_name=doc.code_name,
        code_version=doc.code_version,
        uploaded_by=doc.uploaded_by,
        uploaded_at=doc.uploaded_at,
        status=doc.status,
        s3_key=doc.s3_key,
        extraction_job_id=doc.extraction_job_id,
        rules_extracted=doc.rules_extracted,
        rules_approved=doc.rules_approved,
    )


@router.post(
    "/building-codes/upload",
    response_model=BuildingCodeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_building_code(
    file: Annotated[UploadFile, File(description="Official building code PDF.")],
    jurisdiction: Annotated[str, Query(description="Jurisdiction code e.g. NP-KTM")],
    code_name: Annotated[str, Query(description="Human-readable code name e.g. 'NBC 205:2020'")],
    code_version: Annotated[str, Query(description="Version identifier e.g. 'NBC_2020'")],
    current_user: Annotated[User, Depends(require_permission(Permission.BUILDING_CODES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BuildingCodeDocumentResponse:
    """
    Upload an official building code PDF.

    The file is stored in S3/MinIO and a BuildingCodeDocumentModel record is created
    with status="uploaded". Trigger rule extraction separately via the extract endpoint
    (to be implemented in the LLM extraction job phase).
    """
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only PDF files are accepted. Got: {file.content_type}",
        )

    doc_id = str(uuid.uuid4())
    s3_key = f"{current_user.firm_id}/{doc_id}/{file.filename or 'document.pdf'}"

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    try:
        s3_backend.ensure_bucket_exists(_BUCKET)
        s3_backend.upload_bytes(_BUCKET, s3_key, pdf_bytes, content_type="application/pdf")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to upload file to storage: {exc}",
        )

    doc = await rule_repository.create_document(
        session=session,
        firm_id=current_user.firm_id,
        uploaded_by=current_user.user_id,
        jurisdiction=jurisdiction,
        code_name=code_name,
        code_version=code_version,
        s3_key=s3_key,
    )
    # Override the auto-generated doc_id so the s3_key and doc_id are consistent
    doc.doc_id = doc_id
    session.add(doc)

    return _doc_to_response(doc)


@router.get("/building-codes", response_model=list[BuildingCodeDocumentResponse])
async def list_building_codes(
    current_user: Annotated[User, Depends(require_permission(Permission.BUILDING_CODES))],
    session: Annotated[AsyncSession, Depends(get_session)],
    jurisdiction: Annotated[str | None, Query()] = None,
    doc_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[BuildingCodeDocumentResponse]:
    """
    List building code documents uploaded by this firm.

    Optionally filter by jurisdiction (e.g. "NP-KTM") or status
    ("uploaded", "extracting", "review", "active", "superseded").
    """
    docs = await rule_repository.get_documents(
        session,
        firm_id=current_user.firm_id,
        jurisdiction=jurisdiction,
        status=doc_status,
    )
    return [_doc_to_response(d) for d in docs]


@router.get(
    "/building-codes/{doc_id}/rules",
    response_model=list[ExtractedRuleResponse],
)
async def list_extracted_rules(
    doc_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.BUILDING_CODES))],
    session: Annotated[AsyncSession, Depends(get_session)],
    approved: Annotated[bool | None, Query(description="Filter: true=approved, false=rejected, omit=all")] = None,
) -> list[ExtractedRuleResponse]:
    """
    Return extracted rules for a building code document.

    Use ``approved=null`` (omit) to see the full review queue,
    ``approved=true`` for approved rules, ``approved=false`` for rejections.

    The document must belong to the current user's firm.
    """
    doc = await rule_repository.get_document(session, doc_id, current_user.firm_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    rows = await rule_repository.get_extracted_rules(session, doc_id, approved=approved)
    return [_extracted_rule_to_response(r) for r in rows]


@router.put(
    "/building-codes/{doc_id}/rules/{extracted_rule_id}",
    response_model=ExtractedRuleResponse,
)
async def review_extracted_rule(
    doc_id: str,
    extracted_rule_id: str,
    body: RuleReviewRequest,
    current_user: Annotated[User, Depends(require_permission(Permission.BUILDING_CODES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExtractedRuleResponse:
    """
    Approve or reject a single extracted rule.

    Sets reviewer_approved, reviewer_notes, reviewed_by, and reviewed_at.
    The document must belong to the current user's firm.
    """
    doc = await rule_repository.get_document(session, doc_id, current_user.firm_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    updated = await rule_repository.approve_extracted_rule(
        session=session,
        extracted_rule_id=extracted_rule_id,
        doc_id=doc_id,
        reviewer_id=current_user.user_id,
        approved=body.approved,
        notes=body.notes,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extracted rule not found.")

    return _extracted_rule_to_response(updated)


@router.post(
    "/building-codes/{doc_id}/extract",
    response_model=ExtractionJobStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_rule_extraction(
    doc_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.BUILDING_CODES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExtractionJobStarted:
    """
    Queue a Celery job to extract and verify rules from an uploaded building code PDF.

    The job runs two LLM passes:
      1. Extractor — reads PDF pages in batches and identifies quantitative rules.
      2. Verifier  — cross-checks each extracted rule against its source text.

    Document status transitions: uploaded → extracting → review.
    Rules appear in the review queue once the job completes.
    """
    doc = await rule_repository.get_document(session, doc_id, current_user.firm_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if doc.status not in ("uploaded", "review"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Document is currently '{doc.status}'. "
                "Only 'uploaded' or 'review' documents can be re-extracted."
            ),
        )

    from civilengineer.jobs.code_extraction_job import extract_and_verify_rules  # noqa: PLC0415

    task = extract_and_verify_rules.delay(
        doc_id=doc_id,
        firm_id=current_user.firm_id,
        user_id=current_user.user_id,
    )

    # Store the Celery task ID on the document for status tracking
    doc.extraction_job_id = task.id
    session.add(doc)

    return ExtractionJobStarted(
        doc_id=doc_id,
        celery_task_id=task.id,
        message=(
            "Rule extraction job queued. "
            "Poll GET /building-codes to check when status changes to 'review'."
        ),
    )


@router.post(
    "/building-codes/{doc_id}/activate",
    response_model=ActivateRulesResponse,
)
async def activate_building_code(
    doc_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.BUILDING_CODES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActivateRulesResponse:
    """
    Promote all reviewer-approved extracted rules to JurisdictionRuleModel.

    Updates the document status to "active" and returns the count of rules
    that were promoted. Only firm_admins can activate rules (BUILDING_CODES permission).

    After activation, the rules are immediately available via load_rules_from_db()
    and can be re-indexed into ChromaDB by running:
        uv run python scripts/index_knowledge.py --jurisdiction <code>
    """
    doc = await rule_repository.get_document(session, doc_id, current_user.firm_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if doc.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document rules have already been activated.",
        )

    try:
        count = await rule_repository.activate_approved_rules(
            session=session,
            doc_id=doc_id,
            firm_id=current_user.firm_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return ActivateRulesResponse(
        doc_id=doc_id,
        rules_activated=count,
        jurisdiction=doc.jurisdiction,
        message=(
            f"Activated {count} rules for {doc.jurisdiction}. "
            "Re-index ChromaDB to enable semantic search: "
            f"uv run python scripts/index_knowledge.py --jurisdiction {doc.jurisdiction}"
        ),
    )
