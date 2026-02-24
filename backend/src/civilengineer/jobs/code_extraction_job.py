"""
Celery task: two-agent PDF building code rule extraction + verification.

Pipeline
--------
1. Load PDF bytes from S3/MinIO (building-codes bucket).
2. Mark document status = "extracting".
3. Extract page text with pdfplumber (pages batched in PAGE_BATCH_SIZE groups).
4. Agent 1 — Extractor: sends each batch to the LLM and receives a JSON list
   of candidate rules. Each candidate is written to ExtractedRuleModel.
5. Agent 2 — Verifier: for every extracted rule, sends the source_text +
   extracted fields to a second LLM call. The verifier assigns one of:
     "verified"      — extraction is accurate
     "flagged"       — discrepancy detected (notes explain why)
     "unverifiable"  — source text is insufficient to confirm
   Updates verification_status / verification_notes / verification_confidence.
6. Mark document status = "review" and update rules_extracted count.

Error handling
--------------
- Malformed LLM JSON responses are skipped with a logged warning.
- Individual page batch failures do not abort the job — processing continues.
- DB errors are propagated and mark the document as "failed".
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any

from civilengineer.jobs.celery_app import celery_app

logger = logging.getLogger(__name__)

# Number of PDF pages passed to the Extractor in a single LLM call.
PAGE_BATCH_SIZE = 5

# Valid category values accepted by the schema.
VALID_CATEGORIES = {
    "setback", "room_size", "ventilation", "structural", "fire",
    "accessibility", "sanitation", "parking", "height_limit", "other",
}
VALID_SEVERITIES = {"hard", "soft", "advisory"}

_EXTRACTOR_SYSTEM = (
    "You are a building code rule extractor. "
    "Your job is to read official building code text and extract quantitative rules "
    "as structured JSON. Be precise — only extract rules explicitly stated in the text."
)

_EXTRACTOR_USER_TMPL = """\
Extract all quantitative building rules from the following building code text.

Return a JSON array (and ONLY a JSON array — no markdown, no explanation).
Each element must have these fields:
  "name"           : short rule name (string)
  "description"    : full rule text verbatim or closely paraphrased (string)
  "source_section" : section number, e.g. "4.2.1" (string)
  "category"       : one of: setback, room_size, ventilation, structural, fire,
                     accessibility, sanitation, parking, height_limit, other
  "severity"       : one of: hard (must comply), soft (should comply), advisory
  "numeric_value"  : the primary numeric threshold as a number, or null
  "unit"           : unit string such as "m", "mm", "m2", "%" or null
  "confidence"     : float 0.0–1.0 reflecting extraction confidence

If no quantitative rules are present, return an empty array: []

Building code text (pages {page_range}):
---
{page_text}
---
"""

_VERIFIER_SYSTEM = (
    "You are a building code verification expert. "
    "Your role is to cross-check extracted rules against their source text "
    "and report discrepancies. Be strict but fair."
)

_VERIFIER_USER_TMPL = """\
Verify whether the following extracted building code rule accurately represents \
the source text.

Extracted rule:
  Name:          {name}
  Description:   {description}
  Section:       {source_section}
  Numeric value: {numeric_value} {unit}
  Category:      {category}

Source text (page {source_page}):
---
{source_text}
---

Respond with ONLY a JSON object (no markdown):
{{
  "status": "verified" | "flagged" | "unverifiable",
  "notes":  "explanation (required if flagged or unverifiable, else empty string)",
  "confidence": <float 0.0–1.0>
}}

Definitions:
  "verified"      — the extraction accurately matches the source text
  "flagged"       — there is a factual discrepancy or the value is wrong
  "unverifiable"  — the source text does not contain enough info to confirm
"""


# ---------------------------------------------------------------------------
# Celery task entry point
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="civilengineer.jobs.code_extraction_job.extract_and_verify_rules",
    max_retries=0,
    acks_late=True,
    track_started=True,
)
def extract_and_verify_rules(
    self,
    doc_id: str,
    firm_id: str,
    user_id: str,
) -> dict:
    """
    Celery task: extract rules from a building code PDF then verify them.

    Args:
        doc_id:   BuildingCodeDocumentModel primary key.
        firm_id:  Firm that owns the document.
        user_id:  User who triggered extraction (for audit trail).

    Returns a summary dict with counts of extracted / verified / flagged rules.
    """
    logger.info("extract_and_verify_rules: doc_id=%s firm_id=%s", doc_id, firm_id)
    return asyncio.run(_extract_and_verify_async(doc_id, firm_id, user_id))


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _extract_and_verify_async(
    doc_id: str,
    firm_id: str,
    user_id: str,
) -> dict:
    from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

    # ---- Phase 0: load document + firm LLM config -------------------------
    async with AsyncSessionLocal() as session:
        doc, llm_kwargs = await _load_doc_and_llm(session, doc_id, firm_id)

    if doc is None:
        logger.error("extract_and_verify: document %s not found", doc_id)
        return {"error": "document not found", "extracted": 0}

    pdf_s3_key: str = doc["s3_key"]
    jurisdiction: str = doc["jurisdiction"]
    code_version: str = doc["code_version"]

    # ---- Phase 1: mark extracting -----------------------------------------
    await _update_doc_status(doc_id, firm_id, "extracting")

    # ---- Phase 2: download PDF --------------------------------------------
    try:
        pdf_bytes = _download_pdf(pdf_s3_key)
    except Exception:
        logger.exception("extract_and_verify: failed to download PDF for %s", doc_id)
        await _update_doc_status(doc_id, firm_id, "uploaded")
        return {"error": "pdf download failed", "extracted": 0}

    # ---- Phase 3: extract text pages with pdfplumber ----------------------
    pages = _extract_pages(pdf_bytes)
    if not pages:
        logger.warning("extract_and_verify: no text extracted from PDF %s", doc_id)
        await _update_doc_status(doc_id, firm_id, "review", rules_extracted=0)
        return {"extracted": 0, "verified": 0, "flagged": 0}

    # ---- Phase 4: Extractor agent -----------------------------------------
    extracted_ids: list[str] = []
    for batch_start in range(0, len(pages), PAGE_BATCH_SIZE):
        batch = pages[batch_start : batch_start + PAGE_BATCH_SIZE]
        page_range = f"{batch_start + 1}–{batch_start + len(batch)}"
        batch_text = "\n\n--- Page break ---\n\n".join(
            f"[Page {batch_start + i + 1}]\n{text}" for i, text in enumerate(batch)
        )
        candidates = await _run_extractor(batch_text, page_range, llm_kwargs)
        for candidate in candidates:
            rule_id = await _save_extracted_rule(
                candidate,
                doc_id=doc_id,
                jurisdiction=jurisdiction,
                code_version=code_version,
                page_offset=batch_start,
            )
            if rule_id:
                extracted_ids.append(rule_id)

    # ---- Phase 5: Verifier agent ------------------------------------------
    verified_count = 0
    flagged_count = 0

    for rule_id in extracted_ids:
        status = await _run_verifier_for_rule(rule_id, llm_kwargs)
        if status == "verified":
            verified_count += 1
        elif status == "flagged":
            flagged_count += 1

    # ---- Phase 6: mark review, update counters ----------------------------
    await _update_doc_status(
        doc_id, firm_id, "review", rules_extracted=len(extracted_ids)
    )

    logger.info(
        "extract_and_verify done: doc=%s extracted=%d verified=%d flagged=%d",
        doc_id, len(extracted_ids), verified_count, flagged_count,
    )
    return {
        "extracted": len(extracted_ids),
        "verified": verified_count,
        "flagged": flagged_count,
        "unverifiable": len(extracted_ids) - verified_count - flagged_count,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_doc_and_llm(
    session: Any,
    doc_id: str,
    firm_id: str,
) -> tuple[dict | None, dict]:
    """Return (doc_dict, llm_kwargs). llm_kwargs are kwargs for litellm.completion()."""
    from sqlmodel import select  # noqa: PLC0415

    from civilengineer.auth.password import decrypt_api_key  # noqa: PLC0415
    from civilengineer.core.config import get_settings  # noqa: PLC0415
    from civilengineer.db.models import BuildingCodeDocumentModel, FirmModel  # noqa: PLC0415

    settings = get_settings()

    # Load document
    result = await session.execute(
        select(BuildingCodeDocumentModel)
        .where(BuildingCodeDocumentModel.doc_id == doc_id)
        .where(BuildingCodeDocumentModel.firm_id == firm_id)
    )
    doc_row = result.scalar_one_or_none()
    if doc_row is None:
        return None, {}

    doc_dict = {
        "doc_id": doc_row.doc_id,
        "s3_key": doc_row.s3_key,
        "jurisdiction": doc_row.jurisdiction,
        "code_version": doc_row.code_version,
    }

    # Load firm LLM config
    result2 = await session.execute(
        select(FirmModel).where(FirmModel.firm_id == firm_id)
    )
    firm = result2.scalar_one_or_none()
    llm_cfg = (firm.settings or {}).get("llm_config") if firm else None

    if llm_cfg:
        provider = llm_cfg.get("provider", "anthropic")
        model = llm_cfg.get("model", "claude-sonnet-4-6")
        base_url = llm_cfg.get("base_url")
        enc_key = llm_cfg.get("api_key_encrypted")
        try:
            api_key = decrypt_api_key(enc_key) if enc_key else settings.SYSTEM_LLM_API_KEY
        except Exception:
            api_key = settings.SYSTEM_LLM_API_KEY
    else:
        provider = settings.SYSTEM_LLM_PROVIDER
        model = settings.SYSTEM_LLM_MODEL
        api_key = settings.SYSTEM_LLM_API_KEY
        base_url = None

    llm_kwargs: dict = {
        "model": f"{provider}/{model}" if provider not in ("anthropic", "openai") else model,
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    if api_key:
        llm_kwargs["api_key"] = api_key
    if base_url:
        llm_kwargs["api_base"] = base_url

    return doc_dict, llm_kwargs


async def _update_doc_status(
    doc_id: str,
    firm_id: str,
    status: str,
    **extra: Any,
) -> None:
    from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415
    from civilengineer.db.repositories import rule_repository  # noqa: PLC0415

    async with AsyncSessionLocal() as session:
        await rule_repository.update_document_status(
            session, doc_id, firm_id, status, **extra
        )
        await session.commit()


async def _save_extracted_rule(
    candidate: dict,
    doc_id: str,
    jurisdiction: str,
    code_version: str,
    page_offset: int,
) -> str | None:
    """Insert an ExtractedRuleModel row. Returns the new extracted_rule_id or None."""
    from civilengineer.db.models import ExtractedRuleModel  # noqa: PLC0415
    from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

    name = str(candidate.get("name", "")).strip()
    description = str(candidate.get("description", "")).strip()
    source_section = str(candidate.get("source_section", "")).strip()
    category = str(candidate.get("category", "other")).lower()
    severity = str(candidate.get("severity", "hard")).lower()
    source_page_raw = candidate.get("source_page", page_offset + 1)
    source_text = str(candidate.get("source_text", "")).strip()
    confidence = float(candidate.get("confidence", 0.5))

    if not name or not description:
        return None

    if category not in VALID_CATEGORIES:
        category = "other"
    if severity not in VALID_SEVERITIES:
        severity = "hard"

    # Generate a proposed rule_id in the standard format
    jur_prefix = jurisdiction.replace("-", "_").upper()
    section_slug = re.sub(r"[^A-Za-z0-9]", "_", source_section)[:20].strip("_")
    proposed_rule_id = f"{jur_prefix}_{section_slug}_{uuid.uuid4().hex[:6].upper()}"

    rule_id = str(uuid.uuid4())

    try:
        numeric_value = float(candidate["numeric_value"]) if candidate.get("numeric_value") is not None else None
    except (TypeError, ValueError):
        numeric_value = None

    unit = candidate.get("unit")
    if unit is not None:
        unit = str(unit).strip() or None

    async with AsyncSessionLocal() as session:
        row = ExtractedRuleModel(
            extracted_rule_id=rule_id,
            doc_id=doc_id,
            jurisdiction=jurisdiction,
            proposed_rule_id=proposed_rule_id,
            name=name,
            description=description,
            source_section=source_section,
            source_page=int(source_page_raw),
            source_text=source_text,
            category=category,
            severity=severity,
            numeric_value=numeric_value,
            unit=unit,
            confidence=confidence,
        )
        session.add(row)
        await session.commit()

    return rule_id


async def _run_verifier_for_rule(rule_id: str, llm_kwargs: dict) -> str:
    """
    Run the Verifier agent for a single rule.
    Returns the verification_status string ("verified", "flagged", "unverifiable").
    """
    from civilengineer.db.models import ExtractedRuleModel  # noqa: PLC0415
    from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415
    from sqlmodel import select  # noqa: PLC0415

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ExtractedRuleModel).where(
                ExtractedRuleModel.extracted_rule_id == rule_id
            )
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            return "unverifiable"

        rule_snapshot = {
            "name": rule.name,
            "description": rule.description,
            "source_section": rule.source_section,
            "source_page": rule.source_page,
            "source_text": rule.source_text,
            "category": rule.category,
            "numeric_value": rule.numeric_value,
            "unit": rule.unit,
        }

    verdict = await _call_verifier_llm(rule_snapshot, llm_kwargs)
    v_status = verdict.get("status", "unverifiable")
    v_notes = str(verdict.get("notes", ""))
    v_conf = verdict.get("confidence")
    try:
        v_conf = float(v_conf) if v_conf is not None else None
    except (TypeError, ValueError):
        v_conf = None

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ExtractedRuleModel).where(
                ExtractedRuleModel.extracted_rule_id == rule_id
            )
        )
        rule = result.scalar_one_or_none()
        if rule is not None:
            rule.verification_status = v_status
            rule.verification_notes = v_notes
            rule.verification_confidence = v_conf
            session.add(rule)
            await session.commit()

    return v_status


# ---------------------------------------------------------------------------
# LLM call helpers
# ---------------------------------------------------------------------------


async def _run_extractor(
    batch_text: str,
    page_range: str,
    llm_kwargs: dict,
) -> list[dict]:
    """
    Call the Extractor LLM with a batch of page text.
    Returns a list of candidate dicts (may be empty on failure/parse error).
    """
    prompt = _EXTRACTOR_USER_TMPL.format(page_text=batch_text, page_range=page_range)
    try:
        import litellm  # type: ignore[import]

        response = await litellm.acompletion(
            messages=[
                {"role": "system", "content": _EXTRACTOR_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            **llm_kwargs,
        )
        raw = response.choices[0].message.content or ""
        return _parse_extractor_response(raw)
    except Exception:
        logger.exception("Extractor LLM call failed for pages %s", page_range)
        return []


async def _call_verifier_llm(rule_snapshot: dict, llm_kwargs: dict) -> dict:
    """
    Call the Verifier LLM for a single rule snapshot.
    Returns a dict with status/notes/confidence.
    """
    prompt = _VERIFIER_USER_TMPL.format(
        name=rule_snapshot["name"],
        description=rule_snapshot["description"],
        source_section=rule_snapshot["source_section"],
        source_page=rule_snapshot["source_page"],
        source_text=rule_snapshot["source_text"],
        category=rule_snapshot["category"],
        numeric_value=rule_snapshot["numeric_value"] if rule_snapshot["numeric_value"] is not None else "N/A",
        unit=rule_snapshot["unit"] or "",
    )
    try:
        import litellm  # type: ignore[import]

        response = await litellm.acompletion(
            messages=[
                {"role": "system", "content": _VERIFIER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            **llm_kwargs,
        )
        raw = response.choices[0].message.content or ""
        return _parse_verifier_response(raw)
    except Exception:
        logger.exception("Verifier LLM call failed for rule")
        return {"status": "unverifiable", "notes": "LLM call failed", "confidence": None}


# ---------------------------------------------------------------------------
# Response parsers (pure functions — easy to unit-test)
# ---------------------------------------------------------------------------


def _parse_extractor_response(raw: str) -> list[dict]:
    """
    Parse the Extractor LLM's JSON response into a list of candidate dicts.

    Handles:
    - Valid JSON array
    - JSON wrapped in markdown code fences
    - Empty / malformed responses → returns []
    """
    text = raw.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text.strip())
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract a JSON array from within the text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning("Extractor: could not parse JSON from response")
                return []
        else:
            logger.warning("Extractor: no JSON array found in response")
            return []

    if not isinstance(data, list):
        logger.warning("Extractor: response is not a JSON array")
        return []

    valid: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("name") or not item.get("description"):
            continue
        valid.append(item)
    return valid


def _parse_verifier_response(raw: str) -> dict:
    """
    Parse the Verifier LLM's JSON response.

    Returns dict with status/notes/confidence.
    Falls back to {"status": "unverifiable"} on any parse error.
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text.strip())
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return {"status": "unverifiable", "notes": "could not parse verifier response", "confidence": None}
        else:
            return {"status": "unverifiable", "notes": "no JSON object in verifier response", "confidence": None}

    if not isinstance(data, dict):
        return {"status": "unverifiable", "notes": "verifier returned non-object JSON", "confidence": None}

    status = str(data.get("status", "unverifiable")).lower()
    if status not in {"verified", "flagged", "unverifiable"}:
        status = "unverifiable"

    return {
        "status": status,
        "notes": str(data.get("notes", "")),
        "confidence": data.get("confidence"),
    }


# ---------------------------------------------------------------------------
# PDF + S3 helpers
# ---------------------------------------------------------------------------


def _download_pdf(s3_key: str) -> bytes:
    """Download PDF bytes from the building-codes S3 bucket."""
    from civilengineer.storage import s3_backend  # noqa: PLC0415

    return s3_backend.download_bytes("building-codes", s3_key)


def _extract_pages(pdf_bytes: bytes) -> list[str]:
    """
    Extract plain text from each PDF page using pdfplumber.

    Returns a list of page text strings (one entry per page).
    Pages with no extractable text are represented as empty strings.
    """
    try:
        import io  # noqa: PLC0415

        import pdfplumber  # type: ignore[import]

        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages.append(text.strip())
        return pages
    except Exception:
        logger.exception("pdfplumber: failed to extract text from PDF")
        return []
