# Development Roadmap (v2 — Web Portal)

## Guiding Principles

1. **Prove the hard things first.** The riskiest unknowns are: CAD from ezdxf (plan +
   elevation), OR-Tools solver (multi-floor), and building code PDF extraction. Build
   these before auth or frontend.

2. **Vertical slices.** Each milestone should produce something a real engineer can use.

3. **Nepal first.** Full NBC coverage (NBC 105, NBC 201, NBC 202, NBC 205, NBCR 2072)
   before any other jurisdiction. Use the Nepal implementation as the template for all others.

4. **Desktop-first internally, web-first externally.**
   The core pipeline (Python + solver + ezdxf) runs without a browser.
   Engineers can test the pipeline via FastAPI Swagger UI before the React frontend is built.

5. **Multi-floor from MVP.** The constraint solver and geometry engine handle multiple
   floors (with staircase continuity) from Phase 6. Not an afterthought.

6. **Full 3D output.** The output package includes floor plans + elevation views + 3D
   building outline from Phase 6 onward.

7. **LLM is configurable.** No hardcoded model. Each firm sets their own via admin portal.
   System default used as fallback.

---

## Phase 1 — Core CAD Pipeline (Weeks 1-3)

**Goal:** Python can generate a valid DXF floor plan AND elevation view for a 2-room
layout. No web, no auth, no database. Just prove the core CAD works.

**Deliverables:**
- `pyproject.toml` with all backend dependencies (ezdxf, pdfplumber, shapely, etc.)
- `schemas/design.py` — all core design schemas
- `schemas/elevation.py` — ElevationView, BuildingOutline3D, ElevationSet
- `cad_layer/ezdxf_driver.py` — draw walls, rooms, labels, north arrow
- `cad_layer/layer_manager.py` — AIA standard layers
- `elevation_engine/elevation_generator.py` — basic front elevation from FloorPlan
- `elevation_engine/building_3d.py` — isometric 3D outline
- Hardcoded test: 2-room/2-floor layout → `test_floor_plan.dxf` + `test_elevation.dxf`
- `scripts/test_cad.py` — verify DXF opens correctly in ezdxf

**Success criterion:**
`python scripts/test_cad.py` → produces `test_floor_plan.dxf` + `test_elevation_front.dxf`
that open in any DXF viewer with correct layers, dimensions, and labels.

---

## Phase 2 — Project + Auth Foundation (Weeks 4-6)

**Goal:** Multi-user API with login, firms, LLM config, and project management.

**Deliverables:**
- `db/models.py` — FirmModel (with LLMConfig in settings), UserModel, ProjectModel
- `alembic/` — initial migration
- `auth/` — JWT + bcrypt + RBAC
- `api/routers/auth.py` — login, refresh, logout
- `api/routers/projects.py` — CRUD
- `api/routers/users.py` — basic user management
- `api/routers/admin.py` — LLM config endpoints (GET/PUT /admin/llm-config)
- PostgreSQL + Redis in Docker Compose
- `scripts/seed_db.py` — create first firm + admin user + system default LLM config
- `tests/integration/test_api_auth.py`

**Success criterion:**
```
POST /api/v1/auth/login  → JWT token
PUT  /api/v1/admin/llm-config  → firm LLM settings saved
POST /api/v1/projects    → project created, only visible to same firm
```

---

## Phase 3 — Plot Upload + Analysis (Weeks 7-8)

**Goal:** Engineer uploads a DWG/DXF file; system extracts plot geometry.

**Deliverables:**
- `storage/s3_backend.py` — MinIO integration
- `api/routers/plots.py` — presigned upload URL + notify endpoint
- `plot_analyzer/` — all 4 modules
- `jobs/plot_job.py` — Celery task for async analysis
- `schemas/project.py` — PlotInfo complete
- WebSocket event: `plot.analyzed`
- `tests/unit/test_plot_analyzer.py` — rectangular + irregular DXF fixtures

**Success criterion:**
```
Upload a real site DXF → wait for WebSocket event →
GET /api/v1/projects/{id}/plot → area, facing, polygon returned with confidence ≥ 0.8
```

---

## Phase 4 — Nepal Jurisdiction + Knowledge Base (Weeks 9-11)

**Goal:** Nepal (NP-KTM) jurisdiction fully operational with all codes uploaded and extracted.

**Deliverables:**
- `jurisdiction/registry.py` — Nepal (NP, NP-KTM, NP-PKR) metadata
- `api/routers/admin.py` — building code upload endpoints
  (`POST /admin/building-codes/upload`, `POST /admin/building-codes/{id}/extract`,
   `GET /admin/building-codes/{id}/review`, `POST /admin/building-codes/{id}/activate`)
- `code_parser/pdf_reader.py` — pdfplumber + chunking
- `code_parser/rule_extractor.py` — LLM extraction with structured output
- `code_parser/rule_reviewer.py` — admin review + activation workflow
- `jobs/code_extraction_job.py` — Celery task for PDF extraction
- `db/` migration: `building_code_documents` + `extracted_rules` + `jurisdiction_rules` tables
- `knowledge/indexer.py` — seed ChromaDB from activated rules + PDF chunks
- `reasoning_engine/rule_engine.py` — load rules from PostgreSQL
- Upload + extract all Nepal PDFs: NBC 105, NBC 201, NBC 202, NBC 205, NBCR 2072, KMC Bylaws
- `tests/unit/test_code_parser.py`
- `tests/unit/test_jurisdiction_loader.py -k NP`

**Success criterion:**
```
Upload NBC 205:2012 PDF → extract → review → activate →
loader.get_rule_set("NP-KTM", "NBC_2020_KTM") → rules loaded
query: "minimum bedroom area" → retrieves NP_NBC205_* rule with correct numeric_value
```

---

## Phase 5 — Requirements Interview (Weeks 12-14)

**Goal:** Multi-turn, Nepal-specific interview produces DesignRequirements.

**Deliverables:**
- `requirements_interview/` — all modules
- `requirements_interview/prompts/interview_nepal.md` — Nepal-specific prompt
  (road width question for setback, traditional Newari style option, seismic zone advisory)
- `agent/nodes/interview_node.py`
- `api/routers/interviews.py` — answer + confirm endpoints
- `schemas/project.py` — DesignRequirements complete with multi-floor fields
- `tests/unit/test_interview.py` — mock LLM, verify requirements output

**Success criterion:**
```
Start interview → 8-phase conversation (via Swagger UI) →
Confirm → DesignRequirements JSON saved:
  floors: 2, rooms: [{type: bedroom, floor: 1}, {type: bedroom, floor: 2}, ...]
  jurisdiction: "NP-KTM", seismic_zone: "V"
```

---

## Phase 6 — Constraint Solver + Geometry + Elevation (Weeks 15-18)

**Goal:** Multi-floor solver produces valid room layout + elevation views for Nepal projects.

**Deliverables:**
- `input_layer/validator.py` + `enricher.py` — Nepal setback rules (road-width based)
- `reasoning_engine/constraint_solver.py` — OR-Tools CP-SAT, multi-floor with:
  - Staircase continuity constraint (same x,y position ±0.5m across all floors)
  - Per-floor room packing
  - NBC 105 seismic zone V: no soft storey (ground floor must not be significantly weaker)
- `reasoning_engine/design_advisor.py` — LLM qualitative strategy
- `geometry_engine/` — all 3 modules, multi-floor aware
- `elevation_engine/elevation_generator.py` — generates ElevationSet from BuildingDesign
- `elevation_engine/building_3d.py` — 3D wireframe/isometric
- `elevation_engine/roof_generator.py` — flat/gable/terrace roof geometry
- Full `schemas/design.py` + `schemas/elevation.py`
- `tests/unit/test_constraint_solver.py` — SAT + UNSAT + relaxation, 2-floor
- `tests/unit/test_geometry_engine.py`
- `tests/unit/test_elevation_engine.py`

**Success criterion:**
```
3BHK + 2BHK on 2 floors, 40×60 plot, NP-KTM jurisdiction →
valid multi-floor FloorPlan JSON + ElevationSet in < 60s
All hard rules satisfied: bedroom ≥ 7.0 sqm, kitchen on external wall, etc.
Staircase position aligned between floors (delta < 0.5m)
Front elevation DXF generated with correct floor heights
```

---

## Phase 7 — Full Agent Graph + Design Jobs (Weeks 19-21)

**Goal:** End-to-end design pipeline runs as a Celery background job with elevation output.

**Deliverables:**
- `agent/state.py` + `agent/graph.py` — LangGraph graph (PostgresSaver)
- All agent nodes including `elevation_node`
- `jobs/design_job.py` — Celery task wrapping the agent
- `api/routers/designs.py` — submit + status + approve endpoints
- WebSocket events: `design.progress`, `design.approval_required`, `design.completed`
- `schemas/jobs.py` — DesignJob, JobProgress (with ELEVATION step), ApprovalRequest
- `tests/integration/test_design_job.py`

**Success criterion:**
```
POST /api/v1/projects/{id}/designs → job queued
WebSocket: progress events arrive (SOLVING → GEOMETRY → ELEVATION → AWAITING_APPROVAL)
Status reaches AWAITING_APPROVAL → engineer approves →
floor_plan_F1.dxf + floor_plan_F2.dxf + elevation_front.dxf + building_3d.dxf
appear in S3 → download URLs available
```

---

## Phase 8 — Minimal Frontend (Weeks 22-25)

**Goal:** Engineers can use the system from a browser.

**Deliverables:**
- Next.js 14 project setup (pnpm, TypeScript, Tailwind, shadcn/ui)
- Login / logout flow
- Project list dashboard
- Create project wizard (3 steps, includes number of floors)
- Plot upload + preview
- Interview chat UI (with Nepal-specific question styles)
- Design progress tracker (including ELEVATION step)
- Floor plan viewer (SVG, multi-floor tabs)
- **Elevation viewer (SVG front/rear/side views) — new**
- **3D building outline viewer (isometric SVG) — new**
- File download page (all DXF sheets + PDF set)
- `/admin/llm-config` — LLM provider + model + API key form
- `scripts/generate_api_types.py` — TypeScript types from OpenAPI

**Success criterion:**
An engineer with no knowledge of the backend can:
create a project → upload plot → run interview → approve floor plan + elevations →
download full DXF set + PDF — entirely via browser.

---

## Phase 9 — Building Code Admin + Verification (Weeks 26-27)

**Goal:** Admin can upload building codes; verification layer is complete.

**Deliverables:**
- `/admin/building-codes` — PDF upload UI + extraction status
- `/admin/building-codes/{id}/review` — rule review + approval table
- `verification_layer/` — all 3 modules (Nepal seismic zone V checks added)
- `agent/nodes/verify_node.py` + `revise_node.py`
- Compliance report UI in frontend
- Full MCP toolset (all annotation tools, title block, dimensions)

**Success criterion:**
- Deliberate NBC violation → caught and auto-fixed
- Final DXF set has: plot boundary, setbacks, room labels, dimensions, north arrow, title block
- Admin can upload NBC 105:2020 PDF → extract → review in browser → activate

---

## Phase 10 — India Jurisdiction (Weeks 28-31)

**Goal:** Full NBC 2016 + Maharashtra DCPR coverage.

**Deliverables:**
- Upload + extract: NBC 2016, DCPR 2034, IS 1893 (seismic), Vastu guidelines
- `requirements_interview/prompts/interview_india.md`
- `jurisdiction/registry.py` — IN, IN-MH, IN-KA entries
- Vastu zone enforcement in solver
- `tests/unit/test_jurisdiction_loader.py -k IN`

---

## Phase 11 — USA Jurisdiction (Weeks 32-35)

**Goal:** Full IBC / CBC 2022 support for US projects.

**Deliverables:**
- Upload + extract: IBC 2021, CBC 2022, ADA Standards, Title 24
- `requirements_interview/prompts/interview_usa.md`
- Imperial unit system (feet/inches) throughout
- ADA accessibility checks in verification layer
- `tests/unit/test_jurisdiction_loader.py -k US-CA`

---

## Phase 12 — UK Jurisdiction (Weeks 36-38)

**Deliverables:**
- Upload + extract: Building Regulations Approved Documents (A, B, F, L, M)
- `requirements_interview/prompts/interview_uk.md`
- UK-specific: conservation area advisory, Part M accessibility

---

## Phase 13 — China Jurisdiction (Weeks 39-42)

**Deliverables:**
- Upload + extract: GB 50352-2019, GB 50011-2010 (seismic)
- Interview prompts in English + Chinese
- Multilingual embeddings (paraphrase-multilingual-MiniLM-L12-v2 for CN collection)
- North-south orientation optimization

---

## Phase 14 — Hardening + Production Launch (Weeks 43-47)

**Deliverables:**
- Cloud provider selection + Kubernetes deployment manifests
- CI/CD pipeline (GitHub Actions)
- Sentry + Prometheus + Grafana setup
- Security audit (pen test checklist)
- Performance: end-to-end < 3 minutes for typical 2-floor residential project
- Admin panel: user management + jurisdiction rule overrides
- Real engineer testing: minimum 5 engineers from 2 different jurisdictions
- Rate limiting, file size limits, abuse prevention

---

## Milestone Summary

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 1 | 3 weeks | Core CAD pipeline: floor plan + elevation DXF |
| 2 | 3 weeks | Multi-user API with auth + LLM config |
| 3 | 2 weeks | Plot DWG upload + extraction |
| 4 | 3 weeks | Nepal (NP-KTM) building codes: upload → extract → activate |
| 5 | 3 weeks | Requirements interview (Nepal) |
| 6 | 4 weeks | Multi-floor constraint solver + geometry + elevation engine |
| 7 | 3 weeks | Full agent graph as Celery job |
| 8 | 4 weeks | Usable browser frontend (floor plan + elevation + LLM admin) |
| 9 | 2 weeks | Building code admin UI + verification layer |
| 10 | 4 weeks | India jurisdiction |
| 11 | 4 weeks | USA jurisdiction |
| 12 | 3 weeks | UK jurisdiction |
| 13 | 4 weeks | China jurisdiction |
| 14 | 5 weeks | Production hardening + launch |

**Total: ~47 weeks** (assuming 2–3 engineers, with some parallelization in later phases)

---

## First Milestone

> "A DXF floor plan + a front elevation DXF are generated from a hardcoded Python script
> for a 2-floor, 2-room-per-floor layout. Correct AIA layers, dimensions, and room labels.
> Both files open without errors in any DXF viewer."

This is Phase 1, Week 1. Everything else builds on top of these two proof-of-concept files.
