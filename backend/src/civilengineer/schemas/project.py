"""
Project and plot schemas.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from civilengineer.schemas.design import Point2D


class PlotFacing(StrEnum):
    NORTH = "north"
    SOUTH = "south"
    EAST  = "east"
    WEST  = "west"
    NORTHEAST = "northeast"
    NORTHWEST = "northwest"
    SOUTHEAST = "southeast"
    SOUTHWEST = "southwest"


class PlotInfo(BaseModel):
    """
    Extracted from the uploaded plot DWG/DXF file by the Plot Analyzer.
    Never manually filled — always derived from the file.
    """
    dwg_storage_key: str              # S3 object key for the original file
    polygon: list[Point2D]            # Plot boundary vertices in metres
    area_sqm: float
    width_m: float
    depth_m: float
    is_rectangular: bool
    north_direction_deg: float        # 0 = up (north), 90 = right (east)
    facing: PlotFacing | None = None
    existing_features: list[str] = Field(default_factory=list)
    # e.g. ["tree_nw", "road_south", "existing_wall_east"]
    scale_factor: float               # DWG units → metres
    extraction_confidence: float      # 0.0–1.0
    extraction_notes: list[str] = Field(default_factory=list)


class ProjectProperties(BaseModel):
    """Per-project configuration. Stored as JSONB in PostgreSQL."""
    jurisdiction: str = "NP-KTM"
    jurisdiction_version: str = "NBC_2020_KTM"
    local_body: str | None = None       # "KMC", "MCGM", "LA County"
    special_zone: str | None = None     # "heritage_area", "seismic_zone_V"

    # Nepal-specific
    road_width_m: float | None = None   # Used to compute setbacks

    # Style systems
    vastu_enabled: bool = False
    feng_shui_enabled: bool = False
    accessibility_standard: str = "basic"  # "basic" | "full_ada" | "bs8300"

    # Output preferences
    preferred_output_format: str = "dxf"
    drawing_scale: str = "1:100"
    paper_size: str = "A1"
    dimension_units: str = "meters"        # "meters" | "feet"

    # Firm rule overrides (if firm.settings.custom_rules_enabled)
    rule_overrides: dict[str, Any] = Field(default_factory=dict)

    municipal_approval_notes: str = ""
    engineer_notes: str = ""


class ProjectStatus(StrEnum):
    DRAFT        = "draft"         # Created, no plot yet
    PLOT_PENDING = "plot_pending"  # Plot uploading / analysis running
    READY        = "ready"         # Plot analyzed, interview ready
    IN_PROGRESS  = "in_progress"   # Design job running
    COMPLETED    = "completed"     # At least one successful design
    ARCHIVED     = "archived"


class ProjectSession(BaseModel):
    session_id: str
    project_id: str
    created_by: str                # user_id
    created_at: datetime
    requirements_snapshot: dict    # JSON copy of DesignRequirements at job start
    output_files: list[str] = Field(default_factory=list)  # S3 object keys
    status: str = "pending"        # "pending" | "running" | "completed" | "failed"
    failure_reason: str | None = None
    compliance_summary: dict | None = None


class Project(BaseModel):
    project_id: str
    firm_id: str
    name: str
    client_name: str
    site_address: str
    site_city: str
    site_country: str
    created_by: str                # user_id
    assigned_engineers: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    status: ProjectStatus
    plot_info: PlotInfo | None = None
    properties: ProjectProperties
    requirements: dict | None = None
    sessions: list[ProjectSession] = Field(default_factory=list)


# ------------------------------------------------------------------
# Request / response bodies
# ------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    client_name: str = Field(min_length=1, max_length=200)
    site_address: str = Field(default="")
    site_city: str = Field(min_length=1, max_length=100)
    site_country: str = Field(default="NP")
    jurisdiction: str = Field(default="NP-KTM")
    num_floors: int = Field(default=2, ge=1, le=10)
    road_width_m: float | None = Field(default=None, ge=1.0, le=50.0)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    client_name: str | None = Field(default=None, min_length=1, max_length=200)
    site_address: str | None = None
    properties: dict | None = None


class ProjectListItem(BaseModel):
    """Lightweight summary for project list pages."""
    project_id: str
    name: str
    client_name: str
    site_city: str
    jurisdiction: str
    status: ProjectStatus
    num_sessions: int
    created_at: datetime
    updated_at: datetime
