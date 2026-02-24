"""
Building code schemas — request/response bodies for the admin building code API.

These schemas cover the full PDF → rule extraction → review → activation workflow.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Building code document
# ---------------------------------------------------------------------------


class BuildingCodeDocumentResponse(BaseModel):
    """Response model for a building code PDF document."""
    doc_id: str
    firm_id: str
    jurisdiction: str
    code_name: str
    code_version: str
    uploaded_by: str
    uploaded_at: datetime
    status: str                 # "uploaded" | "extracting" | "review" | "active" | "superseded"
    s3_key: str
    extraction_job_id: str | None
    rules_extracted: int
    rules_approved: int


# ---------------------------------------------------------------------------
# Extracted rules (review queue)
# ---------------------------------------------------------------------------


class ExtractedRuleResponse(BaseModel):
    """Response model for an LLM-extracted rule awaiting review."""
    extracted_rule_id: str
    doc_id: str
    jurisdiction: str
    proposed_rule_id: str
    name: str
    description: str
    source_section: str
    source_page: int
    source_text: str
    category: str
    severity: str
    numeric_value: float | None
    unit: str | None
    confidence: float
    reviewer_approved: bool | None
    reviewer_notes: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    # Verification agent fields
    verification_status: str = "pending"   # "pending" | "verified" | "flagged" | "unverifiable"
    verification_notes: str = ""
    verification_confidence: float | None = None


class RuleReviewRequest(BaseModel):
    """Body for approving or rejecting an extracted rule."""
    approved: bool
    notes: str | None = Field(default=None, description="Optional reviewer notes.")


# ---------------------------------------------------------------------------
# Activation response
# ---------------------------------------------------------------------------


class ActivateRulesResponse(BaseModel):
    """Response after activating approved rules from a document."""
    doc_id: str
    rules_activated: int
    jurisdiction: str
    message: str


class ExtractionJobStarted(BaseModel):
    """Response when a rule-extraction Celery job is queued."""
    doc_id: str
    celery_task_id: str
    message: str
