# Project Structure (v2 — Monorepo)

## Repository Layout

This is a monorepo containing both the backend (Python) and frontend (TypeScript).

```
civilengineer/
│
├── docker-compose.yml               # Local development stack
├── docker-compose.prod.yml          # Production overrides
├── .env.example                     # Template for all env vars
├── .gitignore
├── README.md
│
├── backend/                         # Python backend
│   ├── pyproject.toml               # uv managed
│   ├── uv.lock
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/                # DB migration scripts
│   │
│   ├── configs/
│   │   ├── llm_default.yaml         # System default LLM (used if firm hasn't configured)
│   │   ├── autocad_config.yaml      # COM settings (on-prem, future phase)
│   │   ├── rules_config.yaml        # Solver thresholds
│   │   └── agent_config.yaml        # LangGraph settings
│   │
│   ├── knowledge_base/
│   │   ├── raw/                     # Uploaded building code PDFs (S3 in prod; local in dev)
│   │   │   ├── nepal/
│   │   │   │   ├── nbc_105_2020_seismic.pdf
│   │   │   │   ├── nbc_201_2012_rc.pdf
│   │   │   │   ├── nbc_202_2012_masonry.pdf
│   │   │   │   ├── nbc_205_2012_rules_of_thumb.pdf
│   │   │   │   └── nbcr_2072_regulations.pdf
│   │   │   ├── india/
│   │   │   │   ├── nbc_2016.pdf
│   │   │   │   └── vastu_guidelines.pdf
│   │   │   ├── usa/
│   │   │   │   ├── ibc_2021_excerpts.pdf
│   │   │   │   └── ada_standards.pdf
│   │   │   ├── uk/
│   │   │   │   └── building_regs_approved_docs.pdf
│   │   │   └── china/
│   │   │       └── gb50352_2019.pdf
│   │   └── vector_store/            # ChromaDB (gitignored — rebuilt by workers)
│   │       └── .gitkeep
│   │
│   ├── src/
│   │   └── civilengineer/
│   │       ├── __init__.py
│   │       │
│   │       ├── schemas/             # All Pydantic models — DEFINE FIRST
│   │       │   ├── __init__.py
│   │       │   ├── auth.py          # User, Firm, FirmSettings (incl. LLMConfig), Token
│   │       │   ├── project.py       # Project, ProjectSession, PlotInfo, ProjectProperties
│   │       │   ├── design.py        # DesignRequirements, RoomLayout, FloorPlan, BuildingDesign
│   │       │   ├── elevation.py     # ElevationView, BuildingOutline3D, ElevationSet
│   │       │   ├── rules.py         # DesignRule, RuleSet, JurisdictionCode
│   │       │   ├── codes.py         # BuildingCodeDocument, RuleExtractionJob
│   │       │   ├── mcp.py           # MCPToolCall, MCPToolResult
│   │       │   └── jobs.py          # DesignJob, JobStatus, JobProgress
│   │       │
│   │       ├── db/                  # Database layer
│   │       │   ├── __init__.py
│   │       │   ├── models.py        # SQLModel ORM models (DB tables)
│   │       │   ├── connection.py    # Engine, session factory
│   │       │   ├── migrations.py    # Migration helpers
│   │       │   └── repositories/    # Data access layer
│   │       │       ├── __init__.py
│   │       │       ├── firm_repo.py
│   │       │       ├── user_repo.py
│   │       │       ├── project_repo.py
│   │       │       ├── session_repo.py
│   │       │       └── code_repo.py     # BuildingCodeDocument CRUD
│   │       │
│   │       ├── api/                 # FastAPI application
│   │       │   ├── __init__.py
│   │       │   ├── app.py           # FastAPI app factory + middleware
│   │       │   ├── deps.py          # Dependency injection (get_current_user, etc.)
│   │       │   ├── middleware/
│   │       │   │   ├── auth.py      # JWT validation
│   │       │   │   ├── firm_context.py  # Set PostgreSQL RLS context
│   │       │   │   └── logging.py   # Request/response structlog
│   │       │   └── routers/
│   │       │       ├── __init__.py
│   │       │       ├── auth.py      # POST /auth/login, /auth/refresh, /auth/logout
│   │       │       ├── users.py     # GET/PUT /users/me, admin user management
│   │       │       ├── firms.py     # Firm settings, user management
│   │       │       ├── projects.py  # CRUD /projects
│   │       │       ├── plots.py     # POST /projects/{id}/plot (upload + analyze)
│   │       │       ├── interviews.py # Interview session management
│   │       │       ├── designs.py   # Submit + track design jobs
│   │       │       ├── files.py     # Presigned URL generation for uploads/downloads
│   │       │       └── admin.py     # LLM config + building code management (firm_admin)
│   │       │
│   │       ├── auth/                # Authentication + authorization
│   │       │   ├── __init__.py
│   │       │   ├── jwt.py           # Token create, verify, refresh
│   │       │   ├── password.py      # bcrypt hash + verify
│   │       │   ├── rbac.py          # Permission matrix
│   │       │   └── oauth.py         # Google OAuth (optional)
│   │       │
│   │       ├── storage/             # File storage abstraction
│   │       │   ├── __init__.py
│   │       │   ├── interface.py     # Abstract StorageBackend
│   │       │   ├── s3_backend.py    # AWS S3 / MinIO implementation
│   │       │   └── local_backend.py # Local disk (dev only)
│   │       │
│   │       ├── jobs/                # Celery job definitions
│   │       │   ├── __init__.py
│   │       │   ├── celery_app.py    # Celery app configuration
│   │       │   ├── design_job.py    # Main design pipeline job
│   │       │   ├── plot_job.py      # Plot DWG analysis job
│   │       │   ├── index_job.py     # Knowledge base indexing job
│   │       │   └── code_extraction_job.py  # PDF → rules extraction job (new)
│   │       │
│   │       ├── project_manager/     # Layer 0 — Project lifecycle
│   │       │   ├── __init__.py
│   │       │   └── manager.py       # Thin layer over project_repo
│   │       │
│   │       ├── plot_analyzer/       # Layer 0.5 — DWG reading
│   │       │   ├── __init__.py
│   │       │   ├── dwg_reader.py
│   │       │   ├── boundary_extractor.py
│   │       │   ├── orientation_detector.py
│   │       │   └── site_feature_extractor.py
│   │       │
│   │       ├── requirements_interview/  # Layer 0.75 — Interview
│   │       │   ├── __init__.py
│   │       │   ├── interviewer.py       # LangGraph subgraph
│   │       │   ├── questions.py         # Jurisdiction-aware question bank
│   │       │   ├── interview_state.py
│   │       │   └── prompts/
│   │       │       ├── interview_base.md
│   │       │       ├── interview_nepal.md    # Nepal-specific (first)
│   │       │       ├── interview_india.md
│   │       │       ├── interview_usa.md
│   │       │       ├── interview_uk.md
│   │       │       └── interview_china.md
│   │       │
│   │       ├── input_layer/         # Layer 1 — Validation
│   │       │   ├── __init__.py
│   │       │   ├── validator.py
│   │       │   └── enricher.py
│   │       │
│   │       ├── reasoning_engine/    # Layer 2 — Intelligence
│   │       │   ├── __init__.py
│   │       │   ├── constraint_solver.py   # Multi-floor CP-SAT
│   │       │   ├── rule_engine.py
│   │       │   ├── knowledge_retriever.py
│   │       │   └── design_advisor.py
│   │       │
│   │       ├── geometry_engine/     # Layer 3 — Spatial (per floor)
│   │       │   ├── __init__.py
│   │       │   ├── layout_generator.py    # Multi-floor with staircase continuity
│   │       │   ├── wall_builder.py
│   │       │   └── door_window_placer.py
│   │       │
│   │       ├── elevation_engine/    # Layer 3.5 — Elevation + 3D (new)
│   │       │   ├── __init__.py
│   │       │   ├── elevation_generator.py  # Front/rear/side elevation drawings
│   │       │   ├── building_3d.py          # 3D wireframe/isometric from BuildingDesign
│   │       │   └── roof_generator.py       # Simple roof geometry (flat, gable, hip)
│   │       │
│   │       ├── mcp_server/          # Layer 4 — MCP
│   │       │   ├── __init__.py
│   │       │   ├── server.py
│   │       │   ├── tools/
│   │       │   │   ├── drawing_tools.py
│   │       │   │   ├── element_tools.py
│   │       │   │   ├── annotation_tools.py
│   │       │   │   ├── elevation_tools.py  # Tools for elevation drawing (new)
│   │       │   │   └── file_tools.py
│   │       │   └── bridge/
│   │       │       ├── autocad_client.py
│   │       │       └── connection_guard.py
│   │       │
│   │       ├── cad_layer/           # Layer 5 — CAD generation
│   │       │   ├── __init__.py
│   │       │   ├── ezdxf_driver.py  # Primary: pure Python DXF (plan + elevation + 3D)
│   │       │   ├── com_driver.py    # Optional: win32com AutoCAD (on-prem, future)
│   │       │   ├── driver_factory.py # Choose ezdxf or COM based on config
│   │       │   ├── layer_manager.py
│   │       │   └── error_handler.py
│   │       │
│   │       ├── verification_layer/  # Layer 6 — Self-review
│   │       │   ├── __init__.py
│   │       │   ├── code_compliance.py
│   │       │   ├── spatial_analyzer.py
│   │       │   └── structural_checker.py
│   │       │
│   │       ├── code_parser/         # Layer 7 — Building code PDF extraction (new)
│   │       │   ├── __init__.py
│   │       │   ├── pdf_reader.py        # pdfplumber + PyMuPDF text extraction + chunking
│   │       │   ├── rule_extractor.py    # LLM → structured DesignRule extraction
│   │       │   ├── rule_reviewer.py     # Admin review: stage, approve, activate rules
│   │       │   └── extraction_prompts/
│   │       │       ├── extract_room_rules.md
│   │       │       ├── extract_setback_rules.md
│   │       │       └── extract_structural_rules.md
│   │       │
│   │       ├── agent/               # LangGraph orchestration
│   │       │   ├── __init__.py
│   │       │   ├── state.py
│   │       │   ├── graph.py
│   │       │   └── nodes/
│   │       │       ├── load_project_node.py
│   │       │       ├── interview_node.py
│   │       │       ├── validate_node.py
│   │       │       ├── plan_node.py
│   │       │       ├── solve_node.py          # Multi-floor + staircase continuity
│   │       │       ├── relax_node.py
│   │       │       ├── geometry_node.py       # All floors
│   │       │       ├── elevation_node.py      # New: front/rear/side + 3D outline
│   │       │       ├── approval_pause_node.py # Sends WS event to browser
│   │       │       ├── draw_node.py           # Plan DXF + elevation DXF
│   │       │       ├── verify_node.py
│   │       │       ├── revise_node.py
│   │       │       └── save_output_node.py
│   │       │
│   │       ├── jurisdiction/        # Multi-jurisdiction management
│   │       │   ├── __init__.py
│   │       │   ├── registry.py      # Jurisdiction registry: code → metadata
│   │       │   ├── loader.py        # Load RuleSet for a jurisdiction_code
│   │       │   └── interview_adapter.py # Adapt interview questions by jurisdiction
│   │       │
│   │       └── knowledge/           # Knowledge base management
│   │           ├── __init__.py
│   │           ├── indexer.py
│   │           ├── retriever.py     # Jurisdiction-aware queries
│   │           ├── rule_compiler.py
│   │           └── template_library.py
│   │
│   └── tests/
│       ├── unit/
│       │   ├── test_plot_analyzer.py
│       │   ├── test_constraint_solver.py
│       │   ├── test_rule_engine.py
│       │   ├── test_geometry_engine.py
│       │   ├── test_elevation_engine.py       # New
│       │   ├── test_code_parser.py            # New
│       │   └── test_jurisdiction_loader.py
│       ├── integration/
│       │   ├── test_api_auth.py
│       │   ├── test_api_projects.py
│       │   ├── test_design_job.py
│       │   └── test_agent_graph.py
│       └── fixtures/
│           ├── plots/               # Sample DXF files (Nepal + other jurisdictions)
│           ├── building_codes/      # Sample PDF excerpts for extraction tests
│           ├── sample_requirements_nepal.json
│           ├── sample_requirements_india.json
│           ├── sample_requirements_usa.json
│           └── expected_layouts/
│
├── frontend/                        # Next.js 14 frontend
│   ├── package.json                 # pnpm managed
│   ├── pnpm-lock.yaml
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── components.json              # shadcn/ui config
│   ├── .env.local.example
│   │
│   ├── src/
│   │   ├── app/                     # Next.js App Router
│   │   │   ├── layout.tsx           # Root layout (auth provider, theme)
│   │   │   ├── page.tsx             # Redirect to /dashboard or /login
│   │   │   ├── (auth)/
│   │   │   │   ├── login/
│   │   │   │   │   └── page.tsx
│   │   │   │   └── forgot-password/
│   │   │   │       └── page.tsx
│   │   │   └── (portal)/            # Authenticated section
│   │   │       ├── layout.tsx       # Sidebar + header
│   │   │       ├── dashboard/
│   │   │       │   └── page.tsx     # Projects overview
│   │   │       ├── projects/
│   │   │       │   ├── new/
│   │   │       │   │   └── page.tsx # Create project wizard
│   │   │       │   └── [id]/
│   │   │       │       ├── page.tsx
│   │   │       │       ├── plot/
│   │   │       │       │   └── page.tsx
│   │   │       │       ├── interview/
│   │   │       │       │   └── page.tsx
│   │   │       │       ├── design/
│   │   │       │       │   ├── page.tsx
│   │   │       │       │   └── [sessionId]/
│   │   │       │       │       ├── page.tsx
│   │   │       │       │       └── review/
│   │   │       │       │           └── page.tsx   # Floor plan + elevation approval
│   │   │       │       └── files/
│   │   │       │           └── page.tsx
│   │   │       ├── settings/
│   │   │       │   └── page.tsx
│   │   │       └── admin/           # firm_admin only
│   │   │           ├── users/
│   │   │           │   └── page.tsx
│   │   │           ├── llm-config/
│   │   │           │   └── page.tsx # LLM provider + model + API key config (new)
│   │   │           ├── building-codes/
│   │   │           │   ├── page.tsx         # Upload + manage building code PDFs (new)
│   │   │           │   └── [id]/review/
│   │   │           │       └── page.tsx     # Review + approve extracted rules (new)
│   │   │           └── settings/
│   │   │               └── page.tsx
│   │   │
│   │   ├── components/
│   │   │   ├── ui/                  # shadcn/ui primitives
│   │   │   ├── auth/
│   │   │   │   └── LoginForm.tsx
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   └── Header.tsx
│   │   │   ├── projects/
│   │   │   │   ├── ProjectCard.tsx
│   │   │   │   ├── ProjectList.tsx
│   │   │   │   └── NewProjectWizard.tsx
│   │   │   ├── plot/
│   │   │   │   ├── PlotUpload.tsx
│   │   │   │   └── PlotPreview.tsx
│   │   │   ├── interview/
│   │   │   │   ├── InterviewChat.tsx
│   │   │   │   └── RequirementsSummary.tsx
│   │   │   ├── design/
│   │   │   │   ├── DesignProgress.tsx
│   │   │   │   ├── FloorPlanViewer.tsx      # 2D SVG floor plan (all floors)
│   │   │   │   ├── ElevationViewer.tsx      # Front/rear/side elevation SVG (new)
│   │   │   │   ├── Building3DViewer.tsx     # Isometric 3D outline SVG (new)
│   │   │   │   ├── RoomCard.tsx
│   │   │   │   └── ComplianceReport.tsx
│   │   │   └── admin/
│   │   │       ├── UserTable.tsx
│   │   │       ├── LLMConfigForm.tsx        # LLM provider/model/key form (new)
│   │   │       ├── BuildingCodeUpload.tsx   # PDF upload for building codes (new)
│   │   │       └── RuleReviewTable.tsx      # Review extracted rules (new)
│   │   │
│   │   ├── lib/
│   │   │   ├── api.ts               # API client
│   │   │   ├── auth.ts              # Token management
│   │   │   ├── websocket.ts         # WS connection for design progress
│   │   │   ├── dxf-renderer.ts      # SVG renderer for floor plan JSON
│   │   │   └── elevation-renderer.ts # SVG renderer for elevation JSON (new)
│   │   │
│   │   ├── hooks/
│   │   │   ├── useAuth.ts
│   │   │   ├── useProject.ts
│   │   │   ├── useDesignJob.ts
│   │   │   └── useInterviewSession.ts
│   │   │
│   │   └── types/
│   │       └── api.ts               # TypeScript types from OpenAPI
│
├── infra/                           # Infrastructure as code
│   ├── docker/
│   │   ├── Dockerfile.api
│   │   ├── Dockerfile.worker
│   │   └── Dockerfile.frontend
│   ├── kubernetes/                  # Future — cloud TBD
│   │   ├── api-deployment.yaml
│   │   ├── worker-deployment.yaml
│   │   ├── frontend-deployment.yaml
│   │   ├── postgres-statefulset.yaml
│   │   └── redis-deployment.yaml
│   └── nginx/
│       └── nginx.conf
│
└── scripts/
    ├── seed_db.py                   # Create initial firm + admin user
    ├── index_knowledge.py           # Rebuild ChromaDB vector stores
    ├── extract_rules.py             # CLI to trigger PDF rule extraction (dev tool)
    └── generate_api_types.py        # OpenAPI → TypeScript types
```

---

## Key Conventions

### Separation of Concerns
```
schemas/      ← Data shapes (Pydantic). No DB logic, no business logic.
db/models     ← DB tables (SQLModel). Extends Pydantic schemas.
db/repos      ← Data access. No business logic.
api/routers   ← HTTP handling. Calls services, not repos directly.
jobs/         ← Long-running Celery tasks. Calls pipeline layers.
agent/        ← LangGraph pipeline. Calls domain layers.
[domain]/     ← Domain logic (plot_analyzer, reasoning_engine, etc.)
```

### Multi-tenancy Rule
Every DB query that touches firm data MUST include `firm_id` in the WHERE clause.
The PostgreSQL RLS policy is the safety net, but application code must also filter.

```python
# WRONG:
project = session.get(ProjectModel, project_id)

# RIGHT:
project = session.exec(
    select(ProjectModel)
    .where(ProjectModel.id == project_id)
    .where(ProjectModel.firm_id == current_user.firm_id)
).first()
```

### LLM Config Loading
LLM config is **always** loaded from the firm's database record at job start.
Never use a hardcoded model name inside agent nodes.

```python
# In every Celery task that uses the LLM:
def design_job(job_id: str, firm_id: str, ...):
    firm = firm_repo.get(firm_id)
    llm = get_llm_for_firm(firm)   # reads firm.settings.llm_config
    graph = build_graph(llm=llm)
    graph.invoke(state)
```

### API Error Format (RFC 7807 Problem Details)
```json
{
  "type": "https://civilengineer.app/errors/plot-not-found",
  "title": "Plot Not Found",
  "status": 404,
  "detail": "No plot has been uploaded for project prj_abc123",
  "instance": "/api/projects/prj_abc123/plot"
}
```

### File Naming
- Python: `snake_case.py`
- TypeScript: `PascalCase.tsx` for components, `camelCase.ts` for utilities
- Environment variables: `UPPER_SNAKE_CASE`

### gitignore essentials
```
backend/knowledge_base/vector_store/
backend/.env
frontend/.env.local
projects/
sessions/
*.pyc
__pycache__/
.DS_Store
node_modules/
.next/
```
