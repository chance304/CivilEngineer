# CivilEngineer

A multi-user web portal for civil engineering firms. Engineers log in from any browser,
manage projects, and use a 12-layer AI pipeline to generate professional building drawings
(DXF + PDF) compliant with the project's jurisdiction building codes.

**Core principle:** The LLM handles qualitative reasoning only. Room areas, setbacks,
structural spans, MEP routing, and all numeric constraints are enforced deterministically
from the jurisdiction's compiled rule set. The LLM never makes numeric decisions.

---

## Features

### AI Design Pipeline
- **Conversational interview** — LangGraph subgraph gathers project requirements via chat
- **Constraint solver** — OR-Tools CP-SAT places rooms while satisfying all NBC/IBC rules
- **Geometry engine** — Generates room coordinates, walls, doors, windows (all floors)
- **MEP routing** — A* electrical conduit routing + deterministic plumbing stacking
- **Elevation engine** — Front/rear/left/right elevations + 3D building outline
- **Verification layer** — Compliance checks with auto-revision loop
- **Human review interrupt** — Engineer approves/revises before CAD generation
- **CAD output** — DXF floor plans + MEP sheets + PDF package + IFC (if ifcopenshell installed) + DWG (if ODA CLI installed)

### Building Code System
- Admin uploads official jurisdiction PDFs
- LLM extracts rules → human review → activate
- Rules versioned per project (changing global rules never affects existing projects)
- Supported: Nepal NBC 2020, India NBC 2016, US IBC/CBC, UK Building Regulations

### Multi-Tenancy
- Firm-isolated data via PostgreSQL Row-Level Security
- Roles: `firm_admin` → `senior_engineer` → `engineer` → `viewer`
- JWT auth (15-min access token + 7-day httpOnly refresh cookie)

### Frontend Portal (Next.js 14)
- Dashboard, project creation wizard, plot upload with polygon preview
- Real-time design job progress via WebSocket (8-step timeline)
- SVG floor plan viewer (multi-floor tabs, zoom+pan, compliance badges)
- SVG elevation viewer (front/rear/left/right)
- Isometric 3D building viewer with rotation controls
- Engineer review panel (approve / revise / abort)
- Admin: LLM config, building code PDF upload + rule review, user management

---

## Architecture

```
[0]     Project Manager        → firm/user/project CRUD (PostgreSQL)
[0.5]   Plot Analyzer          → ezdxf reads uploaded DWG → PlotInfo
[0.75]  Requirements Interview → LangGraph subgraph → DesignRequirements (multi-floor)
[1]     Input Validator        → cross-check requirements vs PlotInfo + jurisdiction rules
[2]     Reasoning Engine       → Rule Engine (exact) + ChromaDB (semantic) + OR-Tools (solver)
[3]     Geometry Engine        → room coordinates, walls, doors, windows (all floors, Shapely)
[3.25]  MEP Router             → A* electrical conduit routing + deterministic plumbing stacking
[3.5]   Elevation Engine       → front/rear/side elevations + 3D building outline (ezdxf)
[4]     MCP Tool Server        → FastMCP (stdio) — AI calls ezdxf/AutoCAD tools
[5]     CAD Execution          → ezdxf primary (cloud), AutoCAD COM optional (on-prem)
[6]     Verification Layer     → compliance checks + auto-revision loop
[7]     Code Parser            → PDF → LLM extraction → human review → activate rules
```

---

## Tech Stack

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
| Server State | TanStack Query v5 |
| Client State | Zustand |
| Auth | JWT (python-jose + bcrypt) |

---

## Repository Layout

```
civilengineer/
├── backend/                  Python 3.12 — FastAPI, Celery workers, AI pipeline
│   ├── src/civilengineer/
│   │   ├── api/              FastAPI routers + dependencies
│   │   ├── agent/            LangGraph graph + nodes
│   │   ├── cad_layer/        ezdxf CAD generation
│   │   ├── db/               SQLModel models + repositories + migrations
│   │   ├── elevation_engine/ Front/rear/side elevations + 3D outline
│   │   ├── geometry_engine/  Room layout, walls, doors, windows
│   │   ├── jobs/             Celery design job + code extraction job
│   │   ├── jurisdiction/     Rule loader, registry, unit conversion
│   │   ├── knowledge_base/   ChromaDB vector stores + raw PDFs
│   │   ├── output_layer/     PDF exporter, IFC exporter
│   │   ├── reasoning_engine/ Rule engine, constraint solver, MEP router
│   │   ├── requirements_interview/ Conversational requirements gathering
│   │   └── schemas/          Pydantic schemas (design, MEP, auth, codes)
│   ├── tests/
│   │   ├── unit/             474 unit tests (all mocked)
│   │   └── integration/      Real PostgreSQL + Redis, mocked LLM
│   └── scripts/              DB seed, knowledge index, type generation
├── frontend/                 Next.js 14 — TypeScript, Tailwind, shadcn/ui
│   └── src/
│       ├── app/              App Router pages (auth + portal route groups)
│       ├── components/       Shared UI components
│       ├── hooks/            useAuth, useDesignJob
│       ├── lib/              API client, WebSocket manager, utilities
│       ├── store/            Zustand app store
│       └── types/            Auto-generated API types
├── infra/                    Docker, Kubernetes, Nginx
├── architecture/             Architecture documentation (source of truth)
└── discussion/               Dated progress logs
```

---

## Getting Started

### Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Node.js 20+, pnpm
- Docker + Docker Compose

### Quick Start (Full Stack)

```bash
# 1. Clone and copy env files
git clone https://github.com/your-org/civilengineer
cd civilengineer
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

# 2. Start infrastructure (postgres, redis, minio)
docker compose up -d postgres redis minio

# 3. Backend setup
cd backend
uv sync
uv run alembic upgrade head
uv run python scripts/seed_db.py        # Creates first firm + admin user

# 4. (Optional) Seed Nepal building code rules
uv run python scripts/extract_rules.py --jurisdiction NP-KTM \
  --pdf knowledge_base/raw/nepal/nbc_205_2012.pdf
uv run python scripts/index_knowledge.py --jurisdiction NP-KTM

# 5. Start API + Celery worker
uv run fastapi dev src/civilengineer/api/app.py &
uv run celery -A src.civilengineer.jobs.celery_app worker -Q design,default &

# 6. Start frontend
cd ../frontend
pnpm install
pnpm dev
```

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- MinIO console: http://localhost:9001

### Run Everything with Docker Compose

```bash
docker compose up -d
# Starts: API, Celery worker, PostgreSQL, Redis, MinIO, Next.js frontend
```

---

## Development

### Backend

```bash
cd backend

uv sync                              # Install / sync dependencies
uv run alembic upgrade head          # Apply DB migrations
uv run pytest tests/unit/            # Unit tests (fast, no Docker needed)
uv run pytest tests/integration/     # Integration tests (requires Docker services)
uv run pytest tests/ -v              # All 474 tests
```

### Frontend

```bash
cd frontend

pnpm install
pnpm dev                             # Dev server with hot reload (port 3000)
pnpm build                           # Production build + type check
pnpm lint                            # ESLint strict
pnpm test                            # Vitest component tests
```

### Generate API Types

After changing backend schemas, regenerate TypeScript types:

```bash
cd backend
uv run python scripts/generate_api_types.py
# Writes to: frontend/src/types/api.ts
```

---

## Jurisdiction Coverage

Rules are extracted from uploaded PDFs — no numeric values are hardcoded.

| Code | Jurisdiction | Status |
|------|-------------|--------|
| `NP-KTM` | Nepal — Kathmandu (NBC 2020 + NBC 105 Seismic) | MVP |
| `NP-PKR` | Nepal — Pokhara | MVP |
| `IN-MH` | India — Maharashtra (NBC 2016) | Phase 10 |
| `US-CA` | USA — California (CBC 2022) | Phase 11 |
| `UK` | United Kingdom (Building Regulations 2023) | Phase 12 |

---

## MEP Routing

The MEP (Mechanical, Electrical, Plumbing) routing engine is fully deterministic:

**Electrical:**
- Builds a 0.25m-resolution grid from floor plan walls
- A* pathfinding from panel location to each room cluster
- Wire gauge by circuit type: lighting 2.5 mm², power 6.0 mm², AC 10.0 mm²
- Panel sizing: 1-phase for total ≤ 10 kVA, 3-phase otherwise

**Plumbing:**
- Groups wet rooms (bathroom, kitchen, utility) within 1.5m horizontal offset into shared stacks
- NBC rule enforced: no branch pipes routed through bedroom bounds
- Pipe diameter scales with plumbing grade (basic / standard / premium)

**Output:** Separate MEP DXF sheet with AIA-standard layers (E-CONDUIT, E-PANEL, P-SUPPLY, P-HW-SUPPLY, P-STACK).

---

## Output Files

Each completed design session produces:

| File | Description |
|------|-------------|
| `floor_plan_f{N}.dxf` | Architectural floor plan per floor (ezdxf) |
| `elevation_{direction}.dxf` | Front / rear / left / right elevations |
| `building_3d.dxf` | 3D building outline |
| `mep_f{N}.dxf` | MEP plan per floor (conduit + plumbing) |
| `package.pdf` | Full drawing package (ReportLab) |
| `building.ifc` | IFC 2x3 export (requires ifcopenshell) |
| `floor_plan_f{N}.dwg` | DWG via ODA CLI (if installed) |

---

## Critical Rules

1. **LLM never makes numeric decisions.** Room sizes, setbacks, structural spans, MEP sizing — always from the rule engine.
2. **Every DB query on firm data must include `firm_id` filter.**
3. **ezdxf is the primary CAD driver.** AutoCAD COM is optional, on-prem only.
4. **Rules come from uploaded PDFs — never hardcode numeric rules in code.**
5. **LLM config is always loaded from the firm's database record** at Celery job start.
6. **Rules are versioned.** A project's `jurisdiction_version` is snapshot at creation.
7. **Design jobs run in Celery.** Never run the agent synchronously in an API handler.
8. **Approval pauses use WebSocket events** — the Celery worker polls Redis for engineer responses.
9. **Every completed design session must produce** elevations + 3D + MEP sheets.
10. **MEP routing is fully deterministic** — no LLM involvement in any MEP calculation.

---

## License

Proprietary — all rights reserved.
