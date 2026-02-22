"""
Decision-tracking repository — all DB writes/reads for the 7 decision-tracking tables.

Tables managed:
  - ProjectChangeLogModel     — per-field project change history
  - RequirementsVersionModel  — requirements snapshot per job run
  - DesignDecisionLogModel    — generic one-record-per-node execution log
  - SolverIterationLogModel   — detailed per-solve-run record
  - ComplianceReportModel     — ComplianceReport persisted to PostgreSQL
  - DesignApprovalModel       — engineer interrupt decision
  - ElevationDecisionModel    — roof/elevation choices from draw_node

All write functions are async; they accept an AsyncSession (already managed by
the caller) and do not commit — callers are responsible for session.commit().
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from civilengineer.db.models import (
    ComplianceReportModel,
    DesignApprovalModel,
    DesignDecisionLogModel,
    ElevationDecisionModel,
    ProjectChangeLogModel,
    RequirementsVersionModel,
    SolverIterationLogModel,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# ProjectChangeLogModel
# ---------------------------------------------------------------------------


async def log_project_change(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
    changed_by: str,
    field_name: str,
    old_value: Any,
    new_value: Any,
    change_source: str = "api",
) -> ProjectChangeLogModel:
    """Record a single field change on a project."""
    row = ProjectChangeLogModel(
        log_id=str(uuid4()),
        project_id=project_id,
        firm_id=firm_id,
        changed_by=changed_by,
        changed_at=_utcnow(),
        field_name=field_name,
        old_value=old_value if isinstance(old_value, (dict, list, type(None))) else {"value": old_value},
        new_value=new_value if isinstance(new_value, (dict, list, type(None))) else {"value": new_value},
        change_source=change_source,
    )
    session.add(row)
    return row


async def get_project_change_log(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
) -> list[ProjectChangeLogModel]:
    result = await session.execute(
        select(ProjectChangeLogModel)
        .where(
            ProjectChangeLogModel.project_id == project_id,
            ProjectChangeLogModel.firm_id == firm_id,
        )
        .order_by(ProjectChangeLogModel.changed_at.desc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# RequirementsVersionModel
# ---------------------------------------------------------------------------


async def write_requirements_version(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
    job_id: str,
    session_id: str,
    requirements: dict,
) -> RequirementsVersionModel:
    """Snapshot requirements at job start. Auto-increments version_number per project."""
    # Count existing versions for this project
    count_result = await session.execute(
        select(func.count()).where(RequirementsVersionModel.project_id == project_id)
    )
    version_number = (count_result.scalar() or 0) + 1

    row = RequirementsVersionModel(
        version_id=str(uuid4()),
        project_id=project_id,
        firm_id=firm_id,
        job_id=job_id,
        session_id=session_id,
        captured_at=_utcnow(),
        requirements=requirements,
        version_number=version_number,
    )
    session.add(row)
    logger.debug(
        "RequirementsVersionModel: project=%s job=%s version=%d",
        project_id, job_id, version_number,
    )
    return row


async def get_requirements_versions(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
) -> list[RequirementsVersionModel]:
    result = await session.execute(
        select(RequirementsVersionModel)
        .where(
            RequirementsVersionModel.project_id == project_id,
            RequirementsVersionModel.firm_id == firm_id,
        )
        .order_by(RequirementsVersionModel.version_number.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# DesignApprovalModel
# ---------------------------------------------------------------------------


async def write_design_approval(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
    job_id: str,
    session_id: str,
    approved_by: str,
    decision: str,
    feedback_text: str = "",
    approval_type: str = "floor_plan",
    revision_count: int = 0,
) -> DesignApprovalModel:
    """Record an engineer interrupt decision (approve/revise/abort)."""
    row = DesignApprovalModel(
        approval_id=str(uuid4()),
        project_id=project_id,
        firm_id=firm_id,
        job_id=job_id,
        session_id=session_id,
        approved_by=approved_by,
        approval_type=approval_type,
        decision=decision,
        feedback_text=feedback_text,
        occurred_at=_utcnow(),
        revision_count=revision_count,
    )
    session.add(row)
    logger.info(
        "DesignApprovalModel: project=%s job=%s decision=%s by=%s",
        project_id, job_id, decision, approved_by,
    )
    return row


async def get_design_approvals(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
) -> list[DesignApprovalModel]:
    result = await session.execute(
        select(DesignApprovalModel)
        .where(
            DesignApprovalModel.project_id == project_id,
            DesignApprovalModel.firm_id == firm_id,
        )
        .order_by(DesignApprovalModel.occurred_at.desc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# ComplianceReportModel
# ---------------------------------------------------------------------------


async def write_compliance_report(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
    job_id: str,
    session_id: str,
    compliance_report: dict,
    report_path: str | None = None,
) -> ComplianceReportModel:
    """Persist a ComplianceReport dict to the DB."""
    violations = compliance_report.get("violations", [])
    warnings   = compliance_report.get("warnings", [])
    advisories = compliance_report.get("advisories", [])

    row = ComplianceReportModel(
        report_id=str(uuid4()),
        project_id=project_id,
        firm_id=firm_id,
        job_id=job_id,
        session_id=session_id,
        generated_at=_utcnow(),
        is_compliant=bool(compliance_report.get("compliant", False)),
        violation_count=len(violations),
        warning_count=len(warnings),
        advisory_count=len(advisories),
        hard_violations=violations,
        soft_warnings=warnings,
        advisories=advisories,
        report_path=report_path,
    )
    session.add(row)
    logger.info(
        "ComplianceReportModel: project=%s compliant=%s violations=%d",
        project_id, row.is_compliant, row.violation_count,
    )
    return row


async def get_compliance_reports(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
) -> list[ComplianceReportModel]:
    result = await session.execute(
        select(ComplianceReportModel)
        .where(
            ComplianceReportModel.project_id == project_id,
            ComplianceReportModel.firm_id == firm_id,
        )
        .order_by(ComplianceReportModel.generated_at.desc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Bulk event persistence (DesignDecisionLogModel + SolverIterationLogModel
#                         + ElevationDecisionModel)
# ---------------------------------------------------------------------------


async def persist_decision_events(
    session: AsyncSession,
    events: list[dict],
    project_id: str,
    job_id: str,
    session_id: str,
    firm_id: str,
) -> None:
    """
    Route each accumulated event dict to the correct table.

    Events come from state["decision_events"] accumulated by pipeline nodes.
    Routing logic:
      - node in ("solve", "relax") → SolverIterationLogModel
      - type == "cad_generated"    → ElevationDecisionModel
      - everything else            → DesignDecisionLogModel
    """
    iteration_counter: dict[str, int] = {}  # track iteration_number per (project, job)
    key = f"{project_id}:{job_id}"

    for event in events:
        node      = event.get("node", "")
        etype     = event.get("type", "")
        data      = event.get("data", {})
        iteration = event.get("iteration", 0)
        occurred_at_str = event.get("occurred_at")
        occurred_at = (
            datetime.fromisoformat(occurred_at_str)
            if occurred_at_str
            else _utcnow()
        )

        try:
            if node in ("solve", "relax"):
                iteration_counter[key] = iteration_counter.get(key, 0) + 1
                await _write_solver_iteration(
                    session, project_id, job_id, session_id, firm_id,
                    iteration_number=iteration_counter[key],
                    node=node,
                    data=data,
                    occurred_at=occurred_at,
                )

            elif etype == "cad_generated":
                await _write_elevation_decision(
                    session, project_id, job_id, session_id, firm_id,
                    data=data,
                    occurred_at=occurred_at,
                )

            else:
                session.add(DesignDecisionLogModel(
                    decision_id=str(uuid4()),
                    project_id=project_id,
                    job_id=job_id,
                    session_id=session_id,
                    firm_id=firm_id,
                    node_name=node,
                    occurred_at=occurred_at,
                    decision_type=etype,
                    iteration=iteration,
                    data=data,
                ))

        except Exception as exc:
            logger.warning(
                "persist_decision_events: skipping event node=%s type=%s: %s",
                node, etype, exc,
            )

    logger.debug(
        "persist_decision_events: persisted %d events for project=%s job=%s",
        len(events), project_id, job_id,
    )


async def _write_solver_iteration(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    session_id: str,
    firm_id: str,
    iteration_number: int,
    node: str,
    data: dict,
    occurred_at: datetime,
) -> None:
    """Write a SolverIterationLogModel row from a solve or relax event."""
    row = SolverIterationLogModel(
        iteration_id=str(uuid4()),
        project_id=project_id,
        job_id=job_id,
        session_id=session_id,
        firm_id=firm_id,
        iteration_number=iteration_number,
        started_at=occurred_at,
        solver_status=data.get("status", "UNKNOWN"),
        placed_room_count=data.get("placed_count", 0),
        unplaced_room_count=data.get("unplaced_count", 0),
        solver_time_s=float(data.get("solver_time_s", 0.0)),
        relaxation_type=data.get("relaxation_type"),
        rooms_removed=data.get("rooms_removed", []),
        warnings=data.get("warnings", []),
    )
    session.add(row)


async def _write_elevation_decision(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    session_id: str,
    firm_id: str,
    data: dict,
    occurred_at: datetime,
) -> None:
    """Write an ElevationDecisionModel row from a cad_generated event."""
    dxf_paths = data.get("dxf_paths", [])
    pdf_paths = data.get("pdf_paths", [])

    row = ElevationDecisionModel(
        elevation_id=str(uuid4()),
        project_id=project_id,
        job_id=job_id,
        session_id=session_id,
        firm_id=firm_id,
        decided_at=occurred_at,
        roof_type=data.get("roof_type", ""),
        parapet_height_m=data.get("parapet_height_m"),
        facade_material=data.get("facade_material", ""),
        num_floors=int(data.get("num_floors", 1)),
        floor_heights=data.get("floor_heights", []),
        output_paths=dxf_paths + pdf_paths,
    )
    session.add(row)


# ---------------------------------------------------------------------------
# Query functions (used by API endpoints)
# ---------------------------------------------------------------------------


async def get_project_decisions(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
    job_id: str | None = None,
) -> list[DesignDecisionLogModel]:
    query = select(DesignDecisionLogModel).where(
        DesignDecisionLogModel.project_id == project_id,
        DesignDecisionLogModel.firm_id == firm_id,
    )
    if job_id:
        query = query.where(DesignDecisionLogModel.job_id == job_id)
    query = query.order_by(DesignDecisionLogModel.occurred_at.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_solver_iterations(
    session: AsyncSession,
    project_id: str,
    firm_id: str,
    job_id: str | None = None,
) -> list[SolverIterationLogModel]:
    query = select(SolverIterationLogModel).where(
        SolverIterationLogModel.project_id == project_id,
        SolverIterationLogModel.firm_id == firm_id,
    )
    if job_id:
        query = query.where(SolverIterationLogModel.job_id == job_id)
    query = query.order_by(SolverIterationLogModel.started_at.asc())
    result = await session.execute(query)
    return list(result.scalars().all())
