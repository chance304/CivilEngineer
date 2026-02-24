"""
Projects router — CRUD for project records.

All queries filter by firm_id from the JWT — multi-tenant isolation.
Engineers can only see their own + assigned projects.
Senior engineers and admins see all firm projects.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.auth.rbac import Permission, require_permission
from civilengineer.db.models import (
    ComplianceReportModel,
    DesignApprovalModel,
    DesignDecisionLogModel,
    ProjectAssignmentModel,
    ProjectChangeLogModel,
    ProjectModel,
    RequirementsVersionModel,
    SolverIterationLogModel,
)
from civilengineer.db.session import get_session
from civilengineer.schemas.auth import User, UserRole
from civilengineer.schemas.project import (
    Project,
    ProjectCreate,
    ProjectListItem,
    ProjectProperties,
    ProjectStatus,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _make_project_id() -> str:
    return f"proj_{uuid.uuid4().hex[:12]}"


def _row_to_schema(row: ProjectModel, session_count: int = 0) -> Project:
    props_dict = row.properties or {}
    return Project(
        project_id=row.project_id,
        firm_id=row.firm_id,
        name=row.name,
        client_name=row.client_name,
        site_address=row.site_address,
        site_city=row.site_city,
        site_country=row.site_country,
        created_by=row.created_by,
        assigned_engineers=[],      # Populated separately when needed
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=ProjectStatus(row.status),
        plot_info=None,             # Populated when needed
        properties=ProjectProperties(**props_dict) if props_dict else ProjectProperties(),
        requirements=row.requirements,
        sessions=[],
    )


@router.get("/", response_model=list[ProjectListItem])
async def list_projects(
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    skip: int = 0,
    limit: int = Query(default=50, le=200),
) -> list[ProjectListItem]:
    query = select(ProjectModel).where(ProjectModel.firm_id == current_user.firm_id)

    # Engineers only see their own + assigned projects
    if current_user.role == UserRole.ENGINEER:
        assigned_subq = select(ProjectAssignmentModel.project_id).where(
            ProjectAssignmentModel.user_id == current_user.user_id
        )
        query = query.where(
            (ProjectModel.created_by == current_user.user_id)
            | ProjectModel.project_id.in_(assigned_subq)
        )

    if status_filter:
        query = query.where(ProjectModel.status == status_filter)

    query = query.order_by(ProjectModel.updated_at.desc()).offset(skip).limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()

    return [
        ProjectListItem(
            project_id=r.project_id,
            name=r.name,
            client_name=r.client_name,
            site_city=r.site_city,
            jurisdiction=r.properties.get("jurisdiction", ""),
            status=ProjectStatus(r.status),
            num_sessions=0,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_CREATE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Project:
    now = datetime.now(UTC)
    project_id = _make_project_id()

    properties = {
        "jurisdiction": body.jurisdiction,
        "jurisdiction_version": "NBC_2020_KTM" if body.jurisdiction.startswith("NP") else "default",
        "dimension_units": "meters",
        "num_floors": body.num_floors,
    }
    if body.road_width_m is not None:
        properties["road_width_m"] = body.road_width_m
    if body.site_lat is not None:
        properties["site_lat"] = body.site_lat
    if body.site_lon is not None:
        properties["site_lon"] = body.site_lon

    row = ProjectModel(
        project_id=project_id,
        firm_id=current_user.firm_id,
        name=body.name,
        client_name=body.client_name,
        site_address=body.site_address,
        site_city=body.site_city,
        site_country=body.site_country,
        created_by=current_user.user_id,
        status="draft",
        properties=properties,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return _row_to_schema(row)


@router.get("/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Project:
    row = await _get_project_or_404(project_id, current_user, session)
    return _row_to_schema(row)


@router.patch("/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_UPDATE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Project:
    from civilengineer.db.repositories.decisions_repository import (  # noqa: PLC0415
        log_project_change,
    )

    row = await _get_project_or_404(project_id, current_user, session)

    if body.name is not None:
        await log_project_change(
            session, project_id, current_user.firm_id, current_user.user_id,
            "name", {"value": row.name}, {"value": body.name},
        )
        row.name = body.name
    if body.client_name is not None:
        await log_project_change(
            session, project_id, current_user.firm_id, current_user.user_id,
            "client_name", {"value": row.client_name}, {"value": body.client_name},
        )
        row.client_name = body.client_name
    if body.site_address is not None:
        row.site_address = body.site_address
    if body.properties is not None:
        await log_project_change(
            session, project_id, current_user.firm_id, current_user.user_id,
            "properties", row.properties or {}, body.properties,
        )
        row.properties = {**(row.properties or {}), **body.properties}

    row.updated_at = datetime.now(UTC)
    session.add(row)
    await session.flush()
    return _row_to_schema(row)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_DELETE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    row = await _get_project_or_404(project_id, current_user, session)
    row.status = "archived"
    row.updated_at = datetime.now(UTC)
    session.add(row)


# ------------------------------------------------------------------
# Decision history endpoints
# ------------------------------------------------------------------


@router.get("/{project_id}/decisions", response_model=list[dict])
async def get_project_decisions(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
    job_id: str | None = None,
) -> list[dict]:
    """Return all pipeline node decision events for a project."""
    await _get_project_or_404(project_id, current_user, session)
    query = select(DesignDecisionLogModel).where(
        DesignDecisionLogModel.project_id == project_id,
        DesignDecisionLogModel.firm_id == current_user.firm_id,
    )
    if job_id:
        query = query.where(DesignDecisionLogModel.job_id == job_id)
    query = query.order_by(DesignDecisionLogModel.occurred_at.asc())
    result = await session.execute(query)
    rows = result.scalars().all()
    return [r.model_dump() for r in rows]


@router.get("/{project_id}/solver-iterations", response_model=list[dict])
async def get_solver_iterations(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
    job_id: str | None = None,
) -> list[dict]:
    """Return all constraint-solver run records for a project."""
    await _get_project_or_404(project_id, current_user, session)
    query = select(SolverIterationLogModel).where(
        SolverIterationLogModel.project_id == project_id,
        SolverIterationLogModel.firm_id == current_user.firm_id,
    )
    if job_id:
        query = query.where(SolverIterationLogModel.job_id == job_id)
    query = query.order_by(SolverIterationLogModel.started_at.asc())
    result = await session.execute(query)
    rows = result.scalars().all()
    return [r.model_dump() for r in rows]


@router.get("/{project_id}/compliance-reports", response_model=list[dict])
async def get_compliance_reports(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    """Return all compliance reports for a project."""
    await _get_project_or_404(project_id, current_user, session)
    result = await session.execute(
        select(ComplianceReportModel)
        .where(
            ComplianceReportModel.project_id == project_id,
            ComplianceReportModel.firm_id == current_user.firm_id,
        )
        .order_by(ComplianceReportModel.generated_at.desc())
    )
    rows = result.scalars().all()
    return [r.model_dump() for r in rows]


@router.get("/{project_id}/approvals", response_model=list[dict])
async def get_design_approvals(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    """Return all engineer approval decisions for a project."""
    await _get_project_or_404(project_id, current_user, session)
    result = await session.execute(
        select(DesignApprovalModel)
        .where(
            DesignApprovalModel.project_id == project_id,
            DesignApprovalModel.firm_id == current_user.firm_id,
        )
        .order_by(DesignApprovalModel.occurred_at.desc())
    )
    rows = result.scalars().all()
    return [r.model_dump() for r in rows]


@router.get("/{project_id}/change-log", response_model=list[dict])
async def get_project_change_log(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    """Return the field-level change history for a project."""
    await _get_project_or_404(project_id, current_user, session)
    result = await session.execute(
        select(ProjectChangeLogModel)
        .where(
            ProjectChangeLogModel.project_id == project_id,
            ProjectChangeLogModel.firm_id == current_user.firm_id,
        )
        .order_by(ProjectChangeLogModel.changed_at.desc())
    )
    rows = result.scalars().all()
    return [r.model_dump() for r in rows]


@router.get("/{project_id}/requirements-versions", response_model=list[dict])
async def get_requirements_versions(
    project_id: str,
    current_user: Annotated[User, Depends(require_permission(Permission.PROJECT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    """Return all requirements snapshots for a project (one per job run)."""
    await _get_project_or_404(project_id, current_user, session)
    result = await session.execute(
        select(RequirementsVersionModel)
        .where(
            RequirementsVersionModel.project_id == project_id,
            RequirementsVersionModel.firm_id == current_user.firm_id,
        )
        .order_by(RequirementsVersionModel.version_number.asc())
    )
    rows = result.scalars().all()
    return [r.model_dump() for r in rows]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

async def _get_project_or_404(
    project_id: str,
    current_user: User,
    session: AsyncSession,
) -> ProjectModel:
    result = await session.execute(
        select(ProjectModel).where(
            ProjectModel.project_id == project_id,
            ProjectModel.firm_id == current_user.firm_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    # Engineers need to be creator or assigned
    if current_user.role == UserRole.ENGINEER:
        if row.created_by != current_user.user_id:
            # Check assignment
            assigned = await session.execute(
                select(ProjectAssignmentModel).where(
                    ProjectAssignmentModel.project_id == project_id,
                    ProjectAssignmentModel.user_id == current_user.user_id,
                )
            )
            if assigned.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to this project.",
                )

    return row
