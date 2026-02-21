# AI Architectural Copilot — System Overview (v2)

## What We're Building

A **multi-user web portal** for a civil engineering firm. Engineers log in from any
device/location, manage projects, and use an AI design pipeline to generate
professional-grade building drawings that comply with the correct building codes for
the project's jurisdiction.

**Designed for:** Civil engineers and architects at a firm.
**Access model:** Web browser — no desktop software installation required.
**CAD output:** DXF (plan views + elevation views) + PDF. Optional AutoCAD .dwg for
on-premise deployments. Output includes floor plan + front/rear/side elevations +
3D building outline (isometric).
**Jurisdiction support:** Nepal (NBC) first, then India, USA, UK, China, and more.

---

## Core Design Principles

> **LLM reasoning alone produces amateur results.** Professional-grade output requires:
> LLM (qualitative) + Constraint Solver (numeric enforcement) + Jurisdiction Knowledge Base
> (correct codes) + CAD execution + Self-critique loop.

1. **LLM never makes numeric decisions.** Room areas, setbacks, structural spans —
   all enforced deterministically from the jurisdiction's building code rules.

2. **Building codes come from official documents.** Admin uploads the actual PDF
   building codes. The system extracts rules using LLM and stores them in the
   database. No hand-typed rule JSON files.

3. **LLM is configurable per firm.** Each engineering firm sets their own LLM
   provider, model, and API key via the admin portal. No single hardcoded model.

4. **Full 3D understanding.** Output is not just a floor plan — it includes
   elevation drawings (front, rear, side views) and a 3D building outline, giving
   engineers and clients a complete picture of the proposed building.

5. **Multi-floor from day one.** The MVP supports multi-storey buildings with
   staircase continuity enforcement across floors.

---

## High-Level User Journey

```
1. SIGN IN
   Engineer opens portal in browser → logs in with email + password
   Lands on project dashboard for their firm

2. NEW PROJECT
   Engineer creates a project:
   → Name, client, site location
   → Jurisdiction (Nepal / India-MH / USA-CA / UK / etc.)
   → Number of floors
   → Uploads plot DWG/DXF file

3. PLOT ANALYSIS (automatic)
   System analyzes the uploaded DWG:
   → Extracts plot boundary polygon, area, orientation, scale
   → Shows preview with extracted data for engineer to confirm

4. REQUIREMENTS INTERVIEW
   Engineer clicks "Start Interview"
   → Adaptive multi-turn conversation (browser UI)
   → Questions adapt to jurisdiction and plot (road width for Nepal, vastu for India)
   → Engineer confirms requirements before design runs

5. DESIGN EXECUTION (background job)
   Engineer submits requirements → job queued
   → Real-time progress shown on screen
   → Constraint solver finds valid layout (all floors simultaneously)
   → [APPROVAL PAUSE]: engineer reviews floor plan + elevation preview in browser
   → Approved → full drawings generated (plan + elevations + 3D outline)
   → [VERIFICATION]: AI checks compliance
   → Output files available for download

6. DOWNLOAD + ITERATE
   Engineer downloads DXF (plan + elevations + 3D) + PDF + compliance report
   Can re-run with modified requirements (saved as new session)
   All sessions stored in project history

7. TEAM COLLABORATION
   Senior engineers can review designs by junior engineers
   Project owners can share access with clients (read-only)
   Firm admin manages users, LLM configuration, and project assignments
```

---

## System Architecture (12 Layers)

```
┌─────────────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER                                                  │
│  Next.js 14 (React)  ←  TypeScript + Tailwind CSS + shadcn/ui      │
│  Dashboard | Interview UI | Floor Plan Viewer | Elevation Viewer    │
│  Admin: LLM Config | Building Code Upload | User Management         │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTPS / REST + WebSocket
┌────────────────────────────▼────────────────────────────────────────┐
│  API LAYER                                                           │
│  FastAPI  ←  JWT Auth + RBAC middleware                             │
│  /projects  /interviews  /designs  /users  /admin/llm  /admin/codes │
└────────────────────────────┬────────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  PostgreSQL DB         Redis Cache          S3 File Store
  (projects, users,     (job queue,          (DWG uploads,
   sessions, rules)      websocket events,    DXF/PDF outputs,
                          approval tokens)     building code PDFs)
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│  JOB WORKERS (Celery + Redis)                                       │
│  Design jobs + code extraction jobs run here — async, isolated     │
│                                                                     │
│  [0]   Project Manager      ← Firm/user/project data access        │
│  [0.5] Plot Analyzer        ← ezdxf → PlotInfo extraction          │
│  [0.75] Requirements        ← Interview state → DesignRequirements │
│  [1]   Input Validator      ← Requirements vs PlotInfo + codes     │
│  [2]   Reasoning Engine     ← Rule Engine + ChromaDB + OR-Tools    │
│  [3]   Geometry Engine      ← Coordinates, walls, doors (all flrs) │
│  [3.5] Elevation Engine     ← Front/rear/side elevations + 3D      │
│  [4]   MCP Tool Server      ← AI→CAD bridge (FastMCP, stdio)       │
│  [5]   CAD Execution        ← ezdxf (primary) or AutoCAD (opt.)    │
│  [6]   Verification Layer   ← Compliance check + revision loop     │
│  [7]   Code Parser          ← LLM extraction of rules from PDFs    │
└────────────────────────────────────────────────────────────────────┘
```

---

## Authentication & Access Control

Engineers belong to a **Firm**. Each firm's data is fully isolated from others.

### Roles

| Role | Permissions |
|------|-------------|
| `firm_admin` | Manage users, all projects, firm settings, LLM config, building code uploads |
| `senior_engineer` | All projects, can approve designs by junior engineers |
| `engineer` | Own projects + assigned projects |
| `viewer` | Read-only on assigned projects (for clients, reviewers) |

### Authentication Flow
- Email + password login → JWT access token (15 min) + refresh token (7 days, httpOnly cookie)
- All API calls carry `Authorization: Bearer <token>`
- Role checked on every endpoint via FastAPI dependency injection
- Optional: Google OAuth for firm email domains

---

## LLM Configuration (Per Firm)

Each firm configures their own LLM via the admin portal (`/admin/llm-config`):

| Setting | Options |
|---------|---------|
| Provider | Anthropic, OpenAI, Azure OpenAI, Ollama (self-hosted), custom |
| Model | Any model supported by LiteLLM (e.g., claude-sonnet-4-6, gpt-4o) |
| API Key | Stored encrypted in PostgreSQL, never exposed in frontend |
| Base URL | For Azure or Ollama deployments |
| Temperature | Default 0.3 for design reasoning, configurable |

LiteLLM reads these settings from the firm's record at job start time.
A system-level default model is set in `configs/llm_default.yaml` for firms
that have not yet configured their own.

---

## Multi-Jurisdiction Support

The system automatically loads the correct building codes when a project is created.
**Building codes are not hardcoded** — they are extracted from uploaded PDFs and stored
in the database. See `10-knowledge-base.md` for the full workflow.

### Supported Jurisdictions

| Code | Country / Region | Building Code | Priority |
|------|-----------------|---------------|----------|
| `NP` | Nepal (national) | NBC 2020 + NBC 105 (Seismic) | **MVP — Phase 4** |
| `NP-KTM` | Nepal — Kathmandu Valley | NBC + KMC Bylaws 2079 | **MVP — Phase 4** |
| `NP-PKR` | Nepal — Pokhara | NBC + PMC Bylaws | Phase 4 |
| `IN` | India (national) | NBC 2016 | Phase 10 |
| `IN-MH` | India — Maharashtra | NBC + DCPR 2034 | Phase 10 |
| `IN-KA` | India — Karnataka | NBC + BBMP Bylaws | Phase 10 |
| `US-CA` | USA — California | IBC 2021 + CBC 2022 | Phase 11 |
| `UK` | United Kingdom | Building Regulations 2023 | Phase 12 |
| `CN-SH` | China — Shanghai | GB 50352-2019 | Phase 13 |
| `AU` | Australia | NCC 2022 | Planned |
| `AE-DU` | UAE — Dubai | Dubai BC 2021 | Planned |
| `SG` | Singapore | BCA Regulations | Planned |

---

## Two Human-in-the-Loop Approval Points

**Pause 1 — After Requirements Interview**
Engineer sees a structured summary card in the browser. Confirms or edits any
requirement before the solver runs. No computation wasted on wrong requirements.

**Pause 2 — After Floor Plan Layout + Elevation Preview**
Engineer sees an interactive 2D floor plan preview (all floors) plus front elevation
sketch in the browser. Can approve or request changes.
Feedback is added as constraints before re-solving.

---

## Output Package (Per Design Session)

```
projects/{project_id}/sessions/{session_id}/
├── floor_plan.json          ← Complete multi-floor FloorPlan data (machine-readable)
├── floor_plan_F1.dxf        ← Ground floor plan (AIA layers)
├── floor_plan_F2.dxf        ← First floor plan (one file per floor)
├── elevation_front.dxf      ← Front elevation drawing
├── elevation_rear.dxf       ← Rear elevation drawing
├── elevation_left.dxf       ← Left side elevation
├── elevation_right.dxf      ← Right side elevation
├── building_3d.dxf          ← 3D wireframe / isometric building outline
├── full_set.pdf             ← All sheets combined, print-ready at 1:100
└── report.json              ← Compliance report, warnings, design rationale
```

Note: `.dwg` (proprietary AutoCAD format) is produced only if the Celery worker
has AutoCAD installed with a valid license. The default output is `.dxf` (open format).

---

## Document Index

| File | Contents |
|------|----------|
| 01-tech-decisions.md | Full technology stack with rationale |
| 02-project-structure.md | Monorepo folder/module layout |
| 03-data-schemas.md | All Pydantic/SQLModel data models |
| 04-plot-analyzer.md | DWG/DXF reading strategy |
| 05-requirements-interview.md | Interview flow + adaptive logic |
| 06-reasoning-engine.md | Rules, constraint solver, LLM role |
| 07-mcp-tools.md | MCP tool reference |
| 08-agent-graph.md | LangGraph agent graph design |
| 09-autocad-integration.md | CAD generation (ezdxf + AutoCAD) |
| 10-knowledge-base.md | Building code PDF upload + LLM rule extraction |
| 11-roadmap.md | Development phases |
| 12-authentication.md | Auth system design (JWT + RBAC) |
| 13-api-design.md | REST API endpoints |
| 14-frontend.md | Next.js frontend architecture |
| 15-jurisdiction-codes.md | Building codes by jurisdiction (Nepal first) |
| 16-deployment.md | Infrastructure and deployment |
