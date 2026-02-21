# Data Schemas (v2 — Multi-User + Multi-Jurisdiction)

All schemas use **Pydantic v2**. DB models in `db/models.py` use **SQLModel**
(which extends Pydantic). Define schemas before any other code.

---

## `schemas/auth.py` — Users + Firms

```python
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    FIRM_ADMIN       = "firm_admin"       # Full firm access + user management
    SENIOR_ENGINEER  = "senior_engineer"  # All projects, can approve designs
    ENGINEER         = "engineer"         # Own + assigned projects
    VIEWER           = "viewer"           # Read-only (clients, reviewers)


class Firm(BaseModel):
    """Civil engineering firm. All data is isolated per firm."""
    firm_id: str                        # "firm_abc123"
    name: str                           # "Sharma & Associates Civil Engineers"
    country: str                        # "IN", "US", "GB", "CN"
    default_jurisdiction: str           # "IN" — used as project default
    plan: str = "professional"          # "starter" | "professional" | "enterprise"
    settings: "FirmSettings"
    created_at: datetime


class LLMConfig(BaseModel):
    """
    LLM provider configuration set by firm_admin via the admin portal.
    API key stored encrypted in PostgreSQL — never exposed to frontend.
    LiteLLM reads this at job start time.
    """
    provider: str = "anthropic"             # "anthropic" | "openai" | "azure" | "ollama" | "custom"
    model: str = "claude-sonnet-4-6"        # Any model string LiteLLM accepts
    api_key_encrypted: Optional[str] = None # Encrypted with system SECRET_KEY
    base_url: Optional[str] = None          # For Azure / Ollama / custom deployments
    temperature: float = 0.3               # Default: low temp for design reasoning
    max_tokens: int = 4096


class FirmSettings(BaseModel):
    """Firm-level configuration."""
    autocad_enabled: bool = False       # True if firm has AutoCAD license on workers
    max_concurrent_jobs: int = 5        # How many design jobs can run at once
    custom_rules_enabled: bool = False  # True if firm can override jurisdiction rules
    default_cad_output: str = "dxf"    # "dxf" | "dwg"
    notification_email: Optional[str] = None
    llm_config: Optional[LLMConfig] = None  # None → use system default from llm_default.yaml


class User(BaseModel):
    """Engineer or staff member at a firm."""
    user_id: str                        # "usr_abc123"
    firm_id: str                        # Which firm this user belongs to
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None


class TokenPair(BaseModel):
    """JWT token response on login."""
    access_token: str                   # 15-minute JWT
    token_type: str = "bearer"
    # refresh_token sent as httpOnly cookie (not in body)


class TokenPayload(BaseModel):
    """JWT payload claims."""
    sub: str                            # user_id
    firm_id: str
    role: UserRole
    exp: int                            # Unix timestamp
    iat: int
```

---

## `schemas/project.py` — Projects + Plot

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field
from .design import PlotFacing, Point2D


class JurisdictionCode(str):
    """
    ISO-based jurisdiction identifier.
    Format: {country_code}[-{region_code}]
    Examples: "NP", "NP-KTM", "IN", "IN-MH", "US-CA", "UK", "CN-SH", "AU"
    Nepal (NP, NP-KTM) is the primary MVP jurisdiction.
    """


class PlotInfo(BaseModel):
    """
    Extracted from the plot DWG/DXF file by the Plot Analyzer.
    Never manually filled — always derived from the uploaded file.
    """
    dwg_storage_key: str                # S3 object key for the original file
    polygon: list[Point2D]              # Plot boundary vertices in feet
    area_sqft: float
    width_ft: float
    depth_ft: float
    is_rectangular: bool
    north_direction_deg: float          # 0=up(north), 90=right(east)
    facing: Optional[PlotFacing]
    existing_features: list[str]        # "tree_nw", "road_north", etc.
    scale_factor: float                 # DWG units to feet
    extraction_confidence: float        # 0.0–1.0
    extraction_notes: list[str]         # Assumptions + warnings


class ProjectProperties(BaseModel):
    """
    Per-project configuration that makes each project unique.
    Stored as JSONB in PostgreSQL — flexible, extensible.
    Overrides jurisdiction defaults for this project only.
    """
    # Jurisdiction + regulatory
    jurisdiction: str                   # "IN-MH", "US-CA", etc.
    jurisdiction_version: str           # "NBC_2016", "IBC_2021", etc.
    local_body: Optional[str] = None    # "MCGM", "BBMP", "LA County" — for local setbacks
    special_zone: Optional[str] = None  # "coastal", "seismic_zone_4", "heritage_area"

    # Plot-level overrides (if engineer specifies custom setbacks)
    custom_setback_front_ft: Optional[float] = None
    custom_setback_rear_ft: Optional[float] = None
    custom_setback_left_ft: Optional[float] = None
    custom_setback_right_ft: Optional[float] = None

    # FAR / FSI overrides
    custom_far: Optional[float] = None
    custom_max_coverage_pct: Optional[float] = None

    # Style system
    vastu_enabled: bool = False         # India-specific
    feng_shui_enabled: bool = False     # China-specific (optional)
    accessibility_standard: str = "basic"  # "basic" | "full_ada" | "bs8300"

    # CAD output preferences
    preferred_output_format: str = "dxf"    # "dxf" | "dwg"
    drawing_scale: str = "1:100"
    paper_size: str = "A1"
    dimension_units: str = "feet"       # "feet" | "meters"

    # Firm-level rule overrides (if firm.settings.custom_rules_enabled)
    rule_overrides: dict[str, Any] = Field(default_factory=dict)
    # Example: {"NBC_3.2.1": {"numeric_value": 110.0}}

    # Notes
    municipal_approval_notes: str = ""
    engineer_notes: str = ""


class ProjectStatus(str, Enum):
    DRAFT        = "draft"         # Created, no plot yet
    PLOT_PENDING = "plot_pending"  # Plot uploaded, analysis running
    READY        = "ready"         # Plot analyzed, can start interview
    IN_PROGRESS  = "in_progress"   # Design job running
    COMPLETED    = "completed"     # At least one successful design
    ARCHIVED     = "archived"      # No longer active


class ProjectSession(BaseModel):
    """One design run within a project."""
    session_id: str
    project_id: str
    created_by: str                     # user_id
    created_at: datetime
    requirements_snapshot: dict         # JSON copy of DesignRequirements
    output_files: list[str]             # S3 object keys
    status: str                         # "pending" | "running" | "completed" | "failed"
    failure_reason: Optional[str] = None
    compliance_summary: Optional[dict] = None


class Project(BaseModel):
    """Top-level project record."""
    project_id: str
    firm_id: str                        # Owner firm
    name: str
    client_name: str
    site_address: str
    site_city: str
    site_country: str

    created_by: str                     # user_id
    assigned_engineers: list[str]       # user_ids who can access this project
    created_at: datetime
    updated_at: datetime
    status: ProjectStatus

    plot_info: Optional[PlotInfo] = None
    properties: ProjectProperties
    requirements: Optional[dict] = None  # Latest confirmed DesignRequirements JSON
    sessions: list[ProjectSession] = Field(default_factory=list)
```

---

## `schemas/rules.py` — Building Code Rules (Multi-Jurisdiction)

```python
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class RuleCategory(str, Enum):
    ROOM_SIZE      = "room_size"
    ADJACENCY      = "adjacency"
    SEPARATION     = "separation"
    SETBACK        = "setback"
    VENTILATION    = "ventilation"
    STRUCTURAL     = "structural"
    VASTU          = "vastu"           # India only
    FENG_SHUI      = "feng_shui"       # China optional
    FIRE_SAFETY    = "fire_safety"
    ACCESSIBILITY  = "accessibility"   # ADA (US), BS 8300 (UK), NBC (IN), etc.
    CIRCULATION    = "circulation"
    ENERGY         = "energy"          # Title 24 (CA), Part L (UK), ECBC (IN)
    SEISMIC        = "seismic"         # US/CN/IN seismic zones
    FAR_FSI        = "far_fsi"         # Floor Area Ratio / Floor Space Index


class RuleSeverity(str, Enum):
    HARD     = "hard"       # Must not be violated — solver hard constraint
    SOFT     = "soft"       # Should satisfy — solver penalty
    ADVISORY = "advisory"   # Warning only


class JurisdictionMetadata(BaseModel):
    """Metadata about a jurisdiction's building code system."""
    code: str                           # "IN", "IN-MH", "US-CA"
    country_name: str                   # "India"
    region_name: Optional[str]          # "Maharashtra"
    primary_code: str                   # "NBC 2016" — main building code
    secondary_codes: list[str]          # ["DCPR 2034", "BIS SP 7"] — supplementary
    code_version: str                   # "2016", "2021"
    effective_date: str                 # "2016-01-01"
    unit_system: str                    # "metric" | "imperial" | "mixed"
    language: str                       # "en", "zh", "hi"
    notes: str                          # Special considerations for this jurisdiction


class DesignRule(BaseModel):
    """
    One architectural or building-code rule.
    Source: compiled from knowledge_base/structured/{jurisdiction}/rules.json
    and stored in PostgreSQL jurisdiction_rules table.
    """
    rule_id: str                        # "IN_NBC_3.2.1", "US_IBC_1208.4", "UK_ADM_B2"
    jurisdiction: str                   # "IN", "US-CA", "UK", "CN-SH"
    code_version: str                   # "NBC_2016", "IBC_2021"
    name: str
    description: str
    source: str                         # "NBC India 2016, Part 4, Section 3.2.1"

    category: RuleCategory
    severity: RuleSeverity
    rule_type: str                      # see enum in 06-reasoning-engine.md

    applies_to_room_types: list[str] = Field(default_factory=list)
    numeric_value: Optional[float] = None
    unit: Optional[str] = None          # "sqft" | "sqm" | "ft" | "m"
    reference_room_types: list[str] = Field(default_factory=list)

    # Firm-level override (if firm.settings.custom_rules_enabled)
    is_overridden: bool = False
    override_value: Optional[float] = None
    override_reason: Optional[str] = None

    embedding_text: str = ""            # For ChromaDB indexing
    tags: list[str] = Field(default_factory=list)


class RuleSet(BaseModel):
    """Collection of rules for one jurisdiction + version."""
    jurisdiction: str
    code_version: str
    effective_date: str
    rules: list[DesignRule]
    metadata: JurisdictionMetadata

    def get_hard_rules(self) -> list[DesignRule]:
        return [r for r in self.rules if r.severity == RuleSeverity.HARD]

    def get_rules_for_room(self, room_type: str) -> list[DesignRule]:
        return [
            r for r in self.rules
            if not r.applies_to_room_types or room_type in r.applies_to_room_types
        ]

    def apply_firm_overrides(self, overrides: dict) -> "RuleSet":
        """Apply per-project firm overrides to a copy of this rule set."""
        updated_rules = []
        for rule in self.rules:
            if rule.rule_id in overrides:
                rule = rule.model_copy(update={
                    "is_overridden": True,
                    "override_value": overrides[rule.rule_id].get("numeric_value"),
                    "override_reason": overrides[rule.rule_id].get("reason", "")
                })
            updated_rules.append(rule)
        return self.model_copy(update={"rules": updated_rules})
```

---

## `schemas/jobs.py` — Async Design Jobs

```python
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel


class JobStatus(str, Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    PAUSED     = "paused"        # Waiting for human approval
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class DesignJobStep(str, Enum):
    LOADING       = "loading"
    INTERVIEWING  = "interviewing"
    VALIDATING    = "validating"
    PLANNING      = "planning"
    SOLVING       = "solving"
    GEOMETRY      = "geometry"
    ELEVATION     = "elevation"         # New: generating elevation + 3D views
    AWAITING_APPROVAL = "awaiting_approval"
    DRAWING       = "drawing"
    VERIFYING     = "verifying"
    SAVING        = "saving"
    DONE          = "done"


class JobProgress(BaseModel):
    """
    Real-time progress update sent via WebSocket to the frontend.
    Event type: "design.progress"
    """
    job_id: str
    project_id: str
    session_id: str
    status: JobStatus
    current_step: DesignJobStep
    step_message: str               # Human-readable: "Running constraint solver..."
    progress_pct: int               # 0–100
    solver_iteration: Optional[int] = None
    constraint_relaxed: Optional[str] = None
    error: Optional[str] = None
    floor_plan_summary: Optional[dict] = None  # Set when step = AWAITING_APPROVAL


class DesignJob(BaseModel):
    """Celery job record stored in PostgreSQL."""
    job_id: str
    celery_task_id: str
    project_id: str
    session_id: str
    firm_id: str
    submitted_by: str               # user_id
    submitted_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: JobStatus
    current_step: DesignJobStep
    result: Optional[dict] = None
    error: Optional[str] = None


class ApprovalRequest(BaseModel):
    """
    Data sent to the frontend when agent hits human_review pause.
    Browser shows this and waits for engineer's response.
    """
    job_id: str
    session_id: str
    floor_plan_summary: dict            # Rooms, areas, adjacencies
    compliance_preview: dict            # Which vastu/NBC rules satisfied
    constraints_relaxed: list[str]      # Any soft constraints that were relaxed
    solver_iterations: int


class ApprovalResponse(BaseModel):
    """Engineer's decision from the browser."""
    job_id: str
    approved: bool
    feedback: Optional[str] = None      # If not approved, what to change
```

---

## `db/models.py` — SQLModel ORM Tables

```python
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column, JSON
import sqlalchemy as sa


class FirmModel(SQLModel, table=True):
    __tablename__ = "firms"
    firm_id: str = Field(primary_key=True)
    name: str
    country: str = Field(index=True)
    default_jurisdiction: str
    plan: str = "professional"
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserModel(SQLModel, table=True):
    __tablename__ = "users"
    user_id: str = Field(primary_key=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    email: str = Field(unique=True, index=True)
    full_name: str
    hashed_password: str
    role: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None


class ProjectModel(SQLModel, table=True):
    __tablename__ = "projects"
    project_id: str = Field(primary_key=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    name: str
    client_name: str
    site_address: str
    site_city: str
    site_country: str
    created_by: str = Field(foreign_key="users.user_id")
    status: str = "draft"
    plot_info: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    properties: dict = Field(default_factory=dict, sa_column=Column(JSON))
    requirements: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # RLS: ensured by application, enforced by PostgreSQL policy
    __table_args__ = (
        sa.Index("ix_projects_firm_id_status", "firm_id", "status"),
    )


class ProjectAssignmentModel(SQLModel, table=True):
    __tablename__ = "project_assignments"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.project_id")
    user_id: str = Field(foreign_key="users.user_id")
    assigned_at: datetime = Field(default_factory=datetime.utcnow)


class DesignJobModel(SQLModel, table=True):
    __tablename__ = "design_jobs"
    job_id: str = Field(primary_key=True)
    celery_task_id: str = Field(index=True)
    project_id: str = Field(foreign_key="projects.project_id")
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    session_id: str = Field(index=True)
    submitted_by: str = Field(foreign_key="users.user_id")
    submitted_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"
    current_step: str = "loading"
    result: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    error: Optional[str] = None


class JurisdictionRuleModel(SQLModel, table=True):
    """
    Building code rules stored in PostgreSQL.
    Replaces the flat rules.json files for production.
    Flat JSON files used only for initial seeding via scripts/seed_db.py
    """
    __tablename__ = "jurisdiction_rules"
    rule_id: str = Field(primary_key=True)    # "IN_NBC_3.2.1"
    jurisdiction: str = Field(index=True)
    code_version: str
    category: str = Field(index=True)
    severity: str = Field(index=True)
    rule_type: str
    name: str
    description: str
    source: str
    applies_to: list = Field(default_factory=list, sa_column=Column(JSON))
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    reference_rooms: list = Field(default_factory=list, sa_column=Column(JSON))
    embedding_text: str = ""
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    is_active: bool = True
    effective_from: datetime
    superseded_by: Optional[str] = None      # rule_id of newer version

    __table_args__ = (
        sa.Index("ix_rules_jurisdiction_category", "jurisdiction", "category"),
    )
```

---

## `schemas/codes.py` — Building Code Documents

```python
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class CodeDocumentStatus(str, Enum):
    UPLOADED    = "uploaded"       # PDF stored in S3, not yet processed
    EXTRACTING  = "extracting"     # Celery job running LLM extraction
    REVIEW      = "review"         # Rules extracted, awaiting human review
    ACTIVE      = "active"         # Approved + seeded into jurisdiction_rules
    SUPERSEDED  = "superseded"     # Replaced by a newer upload of the same code


class BuildingCodeDocument(BaseModel):
    """
    Official building code PDF uploaded by firm_admin.
    Rules are extracted from this document via LLM and staged for review.
    """
    doc_id: str
    firm_id: str
    jurisdiction: str               # "NP-KTM", "IN-MH", etc.
    code_name: str                  # "NBC 105:2020 - Seismic Design"
    code_version: str               # "NBC_105_2020"
    uploaded_by: str                # user_id
    uploaded_at: datetime
    s3_key: str                     # Path to PDF in S3
    status: CodeDocumentStatus
    extraction_job_id: Optional[str] = None   # Celery task ID
    rules_extracted: int = 0        # Count of rules found
    rules_approved: int = 0         # Count approved by human reviewer
    extraction_notes: list[str] = []


class RuleExtractionJob(BaseModel):
    """Celery job for extracting rules from a BuildingCodeDocument."""
    job_id: str
    doc_id: str
    firm_id: str
    jurisdiction: str
    status: str                     # "running" | "completed" | "failed"
    chunks_total: int = 0
    chunks_processed: int = 0
    rules_found: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ExtractedRule(BaseModel):
    """
    A rule extracted from a PDF by the LLM — awaiting human review.
    Not yet in jurisdiction_rules table; stored in extracted_rules table.
    """
    extracted_rule_id: str
    doc_id: str
    jurisdiction: str
    proposed_rule_id: str           # Suggested rule_id e.g. "NP_NBC205_4.2"
    name: str
    description: str
    source_section: str             # "NBC 205:2012, Section 4.2, Table 4.1"
    source_page: int                # PDF page number
    source_text: str                # Verbatim text from PDF the rule was derived from
    category: str
    severity: str                   # "hard" | "soft" | "advisory" — LLM's best guess
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    confidence: float               # LLM's confidence 0.0–1.0
    # Review fields
    reviewer_approved: Optional[bool] = None
    reviewer_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
```

---

## `schemas/elevation.py` — Elevation + 3D Building Outline

```python
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class RoofType(str, Enum):
    FLAT      = "flat"
    GABLE     = "gable"
    HIP       = "hip"
    SHED      = "shed"
    TERRACE   = "terrace"    # Flat with parapet, accessible (common in Nepal/India)


class ElevationFace(str, Enum):
    FRONT  = "front"
    REAR   = "rear"
    LEFT   = "left"
    RIGHT  = "right"


class WallOpening(BaseModel):
    """A door or window in an elevation wall, for elevation drawing."""
    opening_type: str           # "door" | "window"
    x_offset_m: float           # From left edge of wall face
    width_m: float
    sill_height_m: float        # From floor (0 for doors)
    height_m: float
    floor_number: int


class ElevationWall(BaseModel):
    """One wall face of the building as seen in an elevation view."""
    face: ElevationFace
    total_width_m: float
    floor_heights_m: list[float]    # Height of each floor (e.g. [3.0, 3.0, 3.0])
    total_height_m: float
    openings: list[WallOpening]
    floor_band_lines: bool = True   # Draw floor band lines between storeys


class ElevationView(BaseModel):
    """One elevation drawing (front, rear, left, or right)."""
    face: ElevationFace
    wall: ElevationWall
    roof_type: RoofType
    roof_height_m: float            # Height of roof ridge above top floor slab
    has_parapet: bool = False
    parapet_height_m: float = 0.9   # Standard parapet height
    label: str                      # "FRONT ELEVATION", "NORTH ELEVATION", etc.


class BuildingOutline3D(BaseModel):
    """
    3D wireframe geometry of the complete building.
    Used to generate the isometric DXF view.
    Defined by floor plans stacked to their heights.
    """
    floor_heights_m: list[float]    # Height of each storey
    roof_type: RoofType
    roof_ridge_height_m: float
    footprint_polygon: list[dict]   # [{x, y}, ...] in meters (same as PlotInfo polygon)
    floor_offset_m: float = 0.0     # Ground floor offset (basement = negative)


class ElevationSet(BaseModel):
    """
    All elevation views + 3D outline for a building design session.
    Generated by elevation_node after geometry_node.
    """
    session_id: str
    project_id: str
    front: ElevationView
    rear: ElevationView
    left: ElevationView
    right: ElevationView
    building_3d: BuildingOutline3D
    # S3 keys set after drawing:
    front_dxf_key: Optional[str] = None
    rear_dxf_key: Optional[str] = None
    left_dxf_key: Optional[str] = None
    right_dxf_key: Optional[str] = None
    building_3d_dxf_key: Optional[str] = None
```

---

## Additional `db/models.py` Tables (Building Code Extraction)

```python
class BuildingCodeDocumentModel(SQLModel, table=True):
    """Uploaded official building code PDF — source for rule extraction."""
    __tablename__ = "building_code_documents"
    doc_id: str = Field(primary_key=True)
    firm_id: str = Field(foreign_key="firms.firm_id", index=True)
    jurisdiction: str = Field(index=True)
    code_name: str
    code_version: str
    uploaded_by: str = Field(foreign_key="users.user_id")
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    s3_key: str
    status: str = "uploaded"        # "uploaded" | "extracting" | "review" | "active" | "superseded"
    extraction_job_id: Optional[str] = None
    rules_extracted: int = 0
    rules_approved: int = 0
    extraction_notes: list = Field(default_factory=list, sa_column=Column(JSON))


class ExtractedRuleModel(SQLModel, table=True):
    """Rules extracted by LLM from a building code PDF — awaiting human review."""
    __tablename__ = "extracted_rules"
    extracted_rule_id: str = Field(primary_key=True)
    doc_id: str = Field(foreign_key="building_code_documents.doc_id", index=True)
    jurisdiction: str = Field(index=True)
    proposed_rule_id: str           # e.g. "NP_NBC205_4.2"
    name: str
    description: str
    source_section: str             # "NBC 205:2012, Section 4.2"
    source_page: int
    source_text: str = Field(sa_column=Column(sa.Text))
    category: str
    severity: str                   # "hard" | "soft" | "advisory"
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    confidence: float               # LLM extraction confidence 0.0–1.0
    reviewer_approved: Optional[bool] = None
    reviewer_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    __table_args__ = (
        sa.Index("ix_extracted_rules_doc_id_status", "doc_id", "reviewer_approved"),
    )
```

---

## Schema Dependency Order

```
1. auth.py       — UserRole, LLMConfig, Firm, FirmSettings, User, TokenPair
2. design.py     — Point2D, Rect2D, enums, DesignRequirements, FloorPlan
3. elevation.py  — ElevationView, BuildingOutline3D, ElevationSet
4. rules.py      — JurisdictionMetadata, DesignRule, RuleSet
5. codes.py      — BuildingCodeDocument, RuleExtractionJob, ExtractedRule
6. project.py    — PlotInfo, ProjectProperties, Project, ProjectSession
7. jobs.py       — DesignJob, JobProgress, ApprovalRequest/Response
8. db/models     — SQLModel ORM versions of all above
```

See `03b-design-schemas.md` for the unchanged design schemas
(DesignRequirements, RoomLayout, FloorPlan, BuildingDesign, WallSegment, etc.)
from the v1 design — those remain the same as the internal pipeline schemas.
