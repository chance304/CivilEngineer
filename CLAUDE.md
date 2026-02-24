# CivilEngineer — CLAUDE.md

## Project Summary

A multi-user web portal for a civil engineering firm. Engineers log in from any
browser, manage projects, and use an AI pipeline to generate professional building
drawings (DXF + PDF + IFC) compliant with the project's jurisdiction building codes.

**Core principle:** The LLM handles qualitative reasoning only. Room areas, setbacks,
structural spans, MEP routing, and all numeric constraints are enforced deterministically
from the jurisdiction's compiled rule set. The LLM never makes numeric decisions.

Full architecture docs: `architecture/` — start with `00-overview.md`.

**Current status (2026-02-24):**
- Backend: **569/569 unit tests passing** — all 12 layers + flooring/finishes, cost estimator, ZIP download, finalized status, client approval
- Frontend: **complete Next.js 14 portal** — 18 pages, 40+ TypeScript files
- Progress log: `progress/2026-02-24.md`

---

## Repository Layout

```
civilengineer/
├── backend/          Python 3.12 — FastAPI, Celery workers, AI pipeline
├── frontend/         Next.js 14 — TypeScript, Tailwind, shadcn/ui
├── infra/            Docker, Kubernetes, Nginx
├── scripts/          DB seed, knowledge index, type generation
└── architecture/     Architecture documentation (source of truth)
```

---

## Common Commands

### Backend (from `backend/`)
```bash
uv sync                              # Install dependencies
uv run alembic upgrade head          # Run DB migrations
uv run python scripts/seed_db.py     # Create first firm + admin user
uv run python scripts/index_knowledge.py --all  # Build ChromaDB vector stores
uv run fastapi dev src/civilengineer/api/app.py  # Dev server (port 8000)
uv run celery -A src.civilengineer.jobs.celery_app worker -Q design,default  # Worker
uv run pytest tests/                 # All tests
uv run pytest tests/unit/            # Unit tests only
uv run pytest tests/integration/ -k auth  # Specific integration tests
```

### Frontend (from `frontend/`)
```bash
pnpm install                         # Install dependencies
pnpm dev                             # Dev server (port 3000)
pnpm build                           # Production build
pnpm lint                            # ESLint
pnpm test                            # Vitest
```

### Full Stack (from root)
```bash
docker compose up -d                 # All services: API, worker, postgres, redis, minio, frontend
docker compose down -v               # Tear down including volumes
docker compose logs -f worker        # Follow worker logs
```

### Type Generation
```bash
uv run python scripts/generate_api_types.py  # OpenAPI → frontend/src/types/api.ts
```

---

## Architecture: 12 Layers + MEP

```
[0]    Project Manager        → firm/user/project CRUD (PostgreSQL)
[0.5]  Plot Analyzer          → ezdxf reads uploaded DWG → PlotInfo
[0.75] Requirements Interview → LangGraph subgraph → DesignRequirements (multi-floor + MEP)
[1]    Input Validator         → cross-check requirements vs PlotInfo + jurisdiction rules
[2]    Reasoning Engine        → Rule Engine (exact) + ChromaDB (semantic) + OR-Tools (solver)
[3]    Geometry Engine         → room coordinates, walls, doors, windows (all floors, Shapely)
[3.25] MEP Router              → A* electrical conduit routing + plumbing stacking (deterministic)
[3.5]  Elevation Engine        → front/rear/side elevations + 3D building outline (ezdxf)
[4]    MCP Tool Server         → FastMCP (stdio) — AI calls ezdxf/AutoCAD tools
[5]    CAD Execution           → ezdxf primary (cloud), AutoCAD COM optional (on-prem, future)
[6]    Verification Layer      → compliance checks + auto-revision loop
[7]    Code Parser             → PDF → LLM extraction → human review → activate rules
```

The entire pipeline runs as a **Celery background job** (`jobs/design_job.py`).
Human approval pauses send WebSocket events to the browser (not CLI blocking).
LangGraph uses `PostgresSaver` (not `SqliteSaver`) for distributed checkpointing.

---

## Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI + Pydantic v2 |
| ORM + Migrations | SQLModel + Alembic |
| Database | PostgreSQL (with Row-Level Security) |
| Job Queue | Celery + Redis |
| Agent Orchestration | LangGraph + LiteLLM |
| Constraint Solver | OR-Tools CP-SAT |
| Vector DB | ChromaDB (per-jurisdiction collections) |
| CAD Generation | ezdxf (primary), AutoCAD COM (optional) |
| File Storage | S3-compatible (MinIO local, AWS/GCS prod) |
| Frontend | Next.js 14 + TypeScript + Tailwind + shadcn/ui |
| State (server) | TanStack Query |
| State (client) | Zustand |
| Auth | JWT (python-jose + bcrypt) |

---

## Multi-Tenancy Rules (Critical)

All data is isolated per `firm_id`. PostgreSQL Row-Level Security enforces this
at the database level. Application code must also filter.

```python
# ALWAYS filter by firm_id in every query touching firm data:
project = session.exec(
    select(ProjectModel)
    .where(ProjectModel.id == project_id)
    .where(ProjectModel.firm_id == current_user.firm_id)
).first()

# NEVER do:
project = session.get(ProjectModel, project_id)  # Missing firm_id check
```

The `firm_context` middleware sets `app.firm_id` PostgreSQL session variable on
every request. RLS policies use this to enforce isolation.

---

## Jurisdiction Handling

Every project has `properties.jurisdiction` (e.g., `"IN-MH"`, `"US-CA"`, `"UK"`).

```python
# Load the correct rule set for a project:
from civilengineer.jurisdiction.loader import get_rule_set
rule_set = get_rule_set(
    jurisdiction=project.properties.jurisdiction,
    code_version=project.properties.jurisdiction_version,
    firm_overrides=project.properties.rule_overrides
)

# Rule ID format: {COUNTRY}_{CODE}_{SECTION}
# Examples: IN_NBC_3.2.1, US_IBC_1208.4, UK_ADM_B5.1
```

Key jurisdiction codes and their primary building codes:
- `NP` / `NP-KTM` / `NP-PKR` → NBC 2020 + NBC 105 (Seismic) **← MVP / Phase 4**
- `IN` / `IN-MH` / `IN-KA` → NBC 2016 (+ state amendments) — Phase 10
- `US-CA` → CBC 2022 (IBC 2021 + California amendments) — Phase 11
- `UK` → Building Regulations 2023 (Approved Documents) — Phase 12
- `CN` / `CN-SH` → GB 50352-2019 — Phase 13

**Rules come from uploaded PDFs, not hand-typed JSON.**
Admin uploads official PDF → extraction job → human review → activate.
See `architecture/10-knowledge-base.md` for the full workflow.

All internal calculations use **meters**. Jurisdiction display units are in
`project.properties.dimension_units` (convert at boundaries only).

Nepal note: land area is often given in ropani (1 ropani = 508.72 m²).
The `jurisdiction/units.py` module handles ropani/anna/dhur → m² conversion.

---

## Authentication + RBAC

Roles (highest to lowest): `firm_admin` → `senior_engineer` → `engineer` → `viewer`

FastAPI dependency pattern:
```python
# Require authenticated user:
user: User = Depends(get_current_user)

# Require specific permission:
user: User = Depends(require_permission(Permission.DESIGN_SUBMIT))

# Check resource ownership in handler:
if project.firm_id != user.firm_id:
    raise HTTPException(403)
```

JWT: access token (15 min, in Authorization header) + refresh token (7 days, httpOnly cookie).

---

## Code Conventions

### Python
- Type annotations everywhere — no `Any` unless truly unavoidable
- Pydantic v2 models for all data shapes; SQLModel for DB tables
- `async def` for all FastAPI route handlers and DB operations
- Repositories in `db/repositories/` for all data access — no raw queries in routers
- Structured logging via `structlog` — always include `firm_id`, `user_id`, `project_id`
- Error responses: RFC 7807 Problem Details format

### TypeScript / React
- Strict TypeScript — no `any`, no `@ts-ignore` without explanation
- Types generated from OpenAPI schema (`scripts/generate_api_types.py`) — do not hand-write API types
- TanStack Query for all server state — no manual fetch in components
- `useAppStore` (Zustand) for cross-component client state only
- All interactive UI elements must be keyboard-accessible (WCAG 2.1 AA)

### SQL / Database
- All migrations via Alembic — never `CREATE TABLE` manually in production
- Every table with firm data must have `firm_id` column + RLS policy
- Use JSONB for flexible/nested data (project properties, rule overrides, plot info)
- Index on `(firm_id, status)` for all filterable tables

### Testing
- Unit tests mock: DB, LLM calls, Celery tasks, S3, AutoCAD COM
- Integration tests use: real PostgreSQL (Docker), real Redis, mocked LLM + solver
- Every new API endpoint needs at least: happy path, auth failure (401), permission failure (403)
- Jurisdiction tests: each new jurisdiction gets `test_jurisdiction_loader.py -k {code}`

---

## Critical Rules (Never Break)

1. **LLM never makes numeric decisions.** Room sizes, setbacks, structural spans —
   always from the rule engine. LLM only reasons about tradeoffs and priorities.

2. **Every DB query on firm data must include `firm_id` filter** — even if RLS is the safety net.

3. **ezdxf is the primary CAD driver.** AutoCAD COM (`com_driver.py`) is optional, on-prem only,
   future phase. Do not add AutoCAD COM dependencies to cloud code paths.

4. **Rules come from uploaded PDFs — never hardcode numeric rules in code.**
   All numeric thresholds must trace to a `JurisdictionRuleModel` row (which traces to a PDF page).

5. **LLM config is always loaded from the firm's database record** at Celery job start.
   Never use a hardcoded model name inside agent nodes or Celery tasks.

6. **Rules are versioned.** A project's `jurisdiction_version` is snapshot at creation.
   Updating the global rule set must not affect existing projects.

7. **Design jobs run in Celery.** Never run the LangGraph agent synchronously in an API handler.

8. **Approval pauses use WebSocket events** — not blocking. The Celery worker polls Redis
   for the engineer's approval response.

9. **Output includes elevations + 3D + MEP.** Every completed design session must produce:
   floor plans (per floor) + elevation DXFs (front/rear/left/right) + building_3d.dxf + MEP DXF sheets + PDF set.

10. **MEP routing is deterministic.** Conduit paths (A*), plumbing stacks, and panel sizing
    are computed algorithmically — never by the LLM. Wire gauges and pipe diameters must
    trace to a `JurisdictionRuleModel` row or the hardcoded NBC defaults in `mep_router.py`.

---

## Key File Paths

```
backend/src/civilengineer/
  schemas/design.py                Core design schemas (DesignRequirements, FloorPlan, etc.)
  schemas/mep.py                   MEP schemas (MEPNetwork, ConduitRun, PlumbingStack, etc.)
  schemas/elevation.py             ElevationView, BuildingOutline3D, ElevationSet
  schemas/codes.py                 BuildingCodeDocument, ExtractedRule, RuleExtractionJob
  schemas/auth.py                  User, Firm, FirmSettings (with LLMConfig), Token schemas
  db/models.py                     SQLModel ORM tables (incl. BuildingCodeDocumentModel)
  db/repositories/                 All data access (query here, not in routers)
  api/app.py                       FastAPI app factory
  api/deps.py                      get_current_user, require_permission
  api/routers/admin.py             LLM config + building code endpoints (firm_admin)
  jobs/design_job.py               Main Celery design pipeline task
  jobs/code_extraction_job.py      PDF → LLM rule extraction Celery task
  agent/graph.py                   LangGraph graph definition (incl. mep_routing_node)
  agent/state.py                   AgentState TypedDict
  agent/nodes/mep_node.py          MEP routing node (between geometry + human_review)
  agent/nodes/elevation_node.py    Generates ElevationSet from BuildingDesign
  jurisdiction/registry.py         All supported jurisdiction metadata (Nepal first)
  jurisdiction/loader.py           get_rule_set(jurisdiction, version, overrides)
  reasoning_engine/constraint_solver.py  OR-Tools CP-SAT (multi-floor)
  reasoning_engine/mep_router.py   A* conduit routing + plumbing stacking
  elevation_engine/                Front/rear/side elevation generator + 3D outline
  output_layer/cost_estimator.py   Room-by-room cost estimate with finish overrides + tier comparison
  output_layer/pdf_exporter.py     PDF package (cover + room schedule + plans + compliance + cost)
  output_layer/ifc_exporter.py     IFC 2x3 BIM export (ifcopenshell, optional)
  code_parser/                     PDF reader + LLM rule extractor + reviewer
  cad_layer/ezdxf_driver.py        Primary CAD generation (plan + elevation + 3D + MEP)
  cad_layer/layer_manager.py       AIA layer definitions (incl. E-CONDUIT, P-SUPPLY, etc.)
  knowledge_base/raw/nepal/        Nepal NBC PDFs (source for extraction)

frontend/src/
  app/(auth)/login/                Sign-in page
  app/(auth)/forgot-password/      Password reset request
  app/(portal)/dashboard/          Project grid + quick actions
  app/(portal)/projects/new/       3-step project creation wizard
  app/(portal)/projects/[id]/plot/ Plot DWG/DXF upload + SVG preview
  app/(portal)/projects/[id]/interview/  WebSocket interview chat
  app/(portal)/projects/[id]/design/[sessionId]/  Pipeline progress timeline
  app/(portal)/projects/[id]/design/[sessionId]/review/  Engineer approval
  app/(portal)/projects/[id]/design/[sessionId]/client-review/  Client sign-off (viewer role)
  app/(portal)/projects/[id]/files/  Output files + ZIP download + finalize gate
  app/(portal)/admin/llm-config/   LLM provider + API key admin page
  app/(portal)/admin/building-codes/ Building code PDF upload + rule review pages
  app/(portal)/admin/users/        User management + invite
  app/(portal)/settings/           Profile + password change
  components/design/FloorPlanViewer.tsx   SVG floor plan renderer (multi-floor, zoom+pan)
  components/design/ElevationViewer.tsx   SVG elevation views (front/rear/left/right)
  components/design/Building3DViewer.tsx  Isometric 3D building outline with rotation
  components/admin/LLMConfigForm.tsx      LLM provider/model/key form + test connection
  components/admin/RuleReviewTable.tsx    Extracted rule review + bulk approve UI
  components/interview/InterviewChat.tsx  WebSocket conversational interview UI
  lib/api.ts                       Typed API client (auto JWT refresh on 401)
  lib/websocket.ts                 Singleton WebSocket manager (auto-reconnect)
  lib/dxf-renderer.ts              FloorPlan JSON → SVG element data (no DXF parser)
  hooks/useDesignJob.ts            Real-time design job WebSocket subscription
  store/useAppStore.ts             Zustand: user, token, jobProgress, approvalRequest
  types/api.ts                     TypeScript interfaces for all API shapes
```

---

## Environment Setup (First Time)

```bash
# 1. Copy env files
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

# 2. Start infrastructure
docker compose up -d postgres redis minio

# 3. Run migrations + seed
cd backend
uv sync
uv run alembic upgrade head
uv run python scripts/seed_db.py

# 4. Upload Nepal building code PDFs via admin portal and extract rules
#    (Or use the dev CLI tool for initial seeding:)
uv run python scripts/extract_rules.py --jurisdiction NP-KTM --pdf knowledge_base/raw/nepal/nbc_205_2012.pdf
uv run python scripts/index_knowledge.py --jurisdiction NP-KTM

# 5. Start API + worker
uv run fastapi dev src/civilengineer/api/app.py &
uv run celery -A src.civilengineer.jobs.celery_app worker -Q design,default &

# 6. Start frontend
cd ../frontend && pnpm install && pnpm dev
```

API docs auto-generated at: `http://localhost:8000/docs`
