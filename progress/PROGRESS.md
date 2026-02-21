# CivilEngineer AI Copilot — Build Progress

> Last updated: 2026-02-19
> Stack: FastAPI · SQLModel · PostgreSQL · Redis · MinIO · Celery · ezdxf · LangGraph · OR-Tools · FastMCP

---

## Summary

| Phase | Name | Status | Tests |
|-------|------|--------|-------|
| 1 | DXF Floor Plan + Elevation Generation | ✅ Complete | 7 DXF files generated |
| 2 | Multi-tenant API — Auth, Projects, Admin | ✅ Complete | 14/14 passing |
| 3 | Plot Upload + DXF Analysis | ✅ Complete | 28/28 passing |
| 4 | Building Code Knowledge Base | ✅ Complete | 48/48 passing |
| 5 | Constraint Solver + Geometry Engine | ✅ Complete | 48/48 passing |
| 6 | Full LangGraph Agent Loop | ✅ Complete | 60/60 passing |
| 7 | Verification Layer + Full Toolset | ✅ Complete | 66/66 passing |
| 8 | Professional Output + Hardening | ✅ Complete | 72/72 passing |
| 9 | API Integration + Design Pipeline Wiring | ✅ Complete | 60/60 passing |

**Total test count: 382/382 passing**

---

## Phase 1 — DXF Floor Plan + Elevation Generation ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/schemas/design.py` | Core spatial schemas: `Point2D`, `Rect2D`, `RoomLayout`, `FloorPlan`, `BuildingDesign` |
| `src/civilengineer/schemas/elevation.py` | Elevation schemas: `ElevationView`, `BuildingElevation` |
| `src/civilengineer/cad_layer/layer_manager.py` | AIA-standard DXF layer definitions (walls, doors, windows, dims, title block) |
| `src/civilengineer/cad_layer/ezdxf_driver.py` | Low-level DXF drawing primitives (walls, doors, windows, room labels, dimensions) |
| `src/civilengineer/elevation_engine/elevation_generator.py` | Generates all 4 elevation views from BuildingDesign |
| `src/civilengineer/elevation_engine/building_3d.py` | 3D building model from floor plan → 4-side elevation data |
| `scripts/test_cad.py` | Smoke-test script → writes 7 DXF files to `output/` |

### What was validated
Running `python scripts/test_cad.py` produces 7 valid DXF files:
- `simple_room.dxf` — single room
- `two_room.dxf` — two adjacent rooms with shared wall
- `floor_plan.dxf` — full 3BHK floor plan (living, kitchen, 3×bedroom, 2×bathroom)
- `elevation_front.dxf` — front elevation
- `elevation_rear.dxf` — rear elevation
- `elevation_left.dxf` — left elevation
- `elevation_right.dxf` — right elevation

---

## Phase 2 — Multi-tenant API ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/core/config.py` | Pydantic Settings from `.env` — DB, Redis, JWT, S3, LLM config |
| `src/civilengineer/schemas/auth.py` | `UserRole`, `LLMConfig`, `FirmSettings`, `User`, `TokenPair`, etc. |
| `src/civilengineer/schemas/project.py` | `PlotInfo`, `ProjectProperties`, `ProjectStatus`, `Project`, `ProjectCreate` |
| `src/civilengineer/schemas/jobs.py` | `JobStatus`, `DesignJobStep`, `JobProgress`, `DesignJob` |
| `src/civilengineer/db/models.py` | 8 SQLModel ORM tables (firms, users, projects, design_jobs, rules, …) |
| `src/civilengineer/db/session.py` | Async SQLAlchemy session factory + `get_session` FastAPI dependency |
| `src/civilengineer/auth/password.py` | bcrypt hashing + Fernet encryption for LLM API keys |
| `src/civilengineer/auth/jwt.py` | JWT creation/decoding with JTI rotation |
| `src/civilengineer/auth/redis_client.py` | Refresh token store/revoke/rotate in Redis |
| `src/civilengineer/auth/rbac.py` | `Permission` enum + `require_permission` FastAPI dependency factory |
| `src/civilengineer/auth/dependencies.py` | `get_current_user` FastAPI dependency |
| `src/civilengineer/api/middleware/firm_context.py` | Sets `request.state.firm_id` from JWT on every request |
| `src/civilengineer/api/routers/auth.py` | `POST /auth/login`, `POST /auth/refresh`, `DELETE /auth/logout` |
| `src/civilengineer/api/routers/projects.py` | Full project CRUD with firm-level isolation + RBAC |
| `src/civilengineer/api/routers/users.py` | `GET /users/me`, user management endpoints |
| `src/civilengineer/api/routers/admin.py` | LLM config CRUD (firm admin only) |
| `src/civilengineer/api/app.py` | FastAPI app factory with CORS, middleware, all routers |
| `docker-compose.yml` | PostgreSQL 16 + Redis 7 + MinIO (with web console on :9001) |
| `.env.example` | Complete environment variable template |
| `alembic.ini` + `alembic/env.py` | Alembic async migrations setup |
| `alembic/versions/20250219_001_initial_schema.py` | Initial migration — all 8 tables |
| `scripts/seed_db.py` | Seeds demo firm + admin + engineer; idempotent |
| `tests/integration/test_api_auth.py` | 14 integration tests using in-memory SQLite + mocked Redis |
| `tests/conftest.py` | Adds `src/` to `sys.path` so tests run without `uv run` |

### Auth design
- **Access token:** 15-minute JWT, `Authorization: Bearer` header
- **Refresh token:** 7-day JWT, stored in httpOnly cookie; JTI written to Redis on login, rotated on each refresh, deleted on logout
- **RBAC roles:** `firm_admin` > `senior_engineer` > `engineer` > `viewer`
- **Multi-tenancy:** every query filters by `firm_id` extracted from JWT

### API endpoints (Phase 2)
```
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
DELETE /api/v1/auth/logout

GET    /api/v1/users/me
PATCH  /api/v1/users/me/password
GET    /api/v1/users/
POST   /api/v1/users/
PATCH  /api/v1/users/{user_id}

GET    /api/v1/projects/
POST   /api/v1/projects/
GET    /api/v1/projects/{id}
PATCH  /api/v1/projects/{id}
DELETE /api/v1/projects/{id}

GET    /api/v1/admin/llm-config
PUT    /api/v1/admin/llm-config
POST   /api/v1/admin/llm-config/test
DELETE /api/v1/admin/llm-config
```

---

## Phase 3 — Plot Upload + DXF Analysis ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/storage/s3_backend.py` | boto3 S3/MinIO client — presigned PUT/GET URLs, upload/download bytes |
| `src/civilengineer/plot_analyzer/boundary_extractor.py` | 3-strategy extractor: named layer → largest polygon → HATCH fallback |
| `src/civilengineer/plot_analyzer/orientation_detector.py` | North detection: NORTH block → TEXT entity → assume 0° |
| `src/civilengineer/plot_analyzer/site_feature_extractor.py` | Tree, road, water, existing-structure detection from blocks/layers/text |
| `src/civilengineer/plot_analyzer/dwg_reader.py` | Entry point — reads INSUNITS header, applies unit scale, returns `PlotInfo` |
| `src/civilengineer/jobs/celery_app.py` | Celery app with Redis broker |
| `src/civilengineer/jobs/plot_job.py` | `analyze_plot` task: S3 download → DXF analysis → DB save → Redis pub/sub event |
| `src/civilengineer/api/routers/plots.py` | Plot upload-URL, notify, and get-plot-info endpoints |
| `src/civilengineer/api/websocket.py` | `ConnectionManager` + `redis_pubsub_listener` coroutine |
| `src/civilengineer/api/routers/ws.py` | `WS /api/v1/ws/{project_id}?token=<jwt>` real-time event endpoint |
| `tests/unit/test_plot_analyzer.py` | 28 unit tests — 8 fixture classes covering all extraction strategies |

### DXF analysis capabilities
- **Unit conversion:** INSUNITS header (mm, cm, m, ft, in) → all output in metres
- **Boundary extraction confidence:**
  - Named layer (`C-PLOT`, `PLOT`, `BOUNDARY`, …): **0.95**
  - Largest closed polygon: **0.75**
  - HATCH entity: **0.55**
  - Not found: **0.0**
- **North detection:** block insertions (NORTH_ARROW, COMPASS, …) → TEXT entities → default 0°
- **Facing derived** from north angle → `PlotFacing` enum (N/S/E/W + diagonals)
- **Site features:** trees, roads, water bodies, drains, wells, existing structures, parking

### Upload flow
```
1. GET  /api/v1/projects/{id}/plot/upload-url
        ← { upload_url (presigned S3 PUT), storage_key, expires_in: 3600 }

2. Client PUTs DXF bytes directly to MinIO (no API proxy)

3. POST /api/v1/projects/{id}/plot  body: { storage_key, filename }
        ← { job_id, status: "pending" }
        → project.status = "plot_pending"
        → Celery task queued

4. Celery worker:
        → downloads DXF from S3
        → runs DXF analyser
        → saves PlotInfo to project (JSON column)
        → project.status = "ready" (confidence ≥ 0.5) or "draft"
        → publishes Redis event on channel project:{id}:events

5. GET  /api/v1/projects/{id}/plot
        ← full PlotInfo JSON (404 until analysis completes)

6. WS   /api/v1/ws/{id}?token=<jwt>
        ← { "type": "plot.analyzed", "confidence": 0.95, "area_sqm": 600.0, … }
```

### New API endpoints (Phase 3)
```
GET  /api/v1/projects/{id}/plot/upload-url
POST /api/v1/projects/{id}/plot
GET  /api/v1/projects/{id}/plot

WS   /api/v1/ws/{project_id}?token=<access_token>
```

---

## What Can Be Tested Right Now

### 1. Plot Analyser — Unit Tests (no infrastructure needed)
```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_plot_analyzer.py -v
# Expected: 28/28 PASSED
```

### 2. Auth + Projects + Admin — Integration Tests (no PostgreSQL or Redis needed)
```bash
cd backend
.venv/bin/python -m pytest tests/integration/test_api_auth.py -v
# Expected: 14/14 PASSED  (uses in-memory SQLite + mocked Redis)
```

### 3. Rule Engine — Unit Tests (no infrastructure needed)
```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_rule_engine.py -v
# Expected: 48/48 PASSED
```

### 4. Constraint Solver — Unit Tests (no infrastructure needed)
```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_constraint_solver.py -v
# Expected: 48/48 PASSED
```

### 5. Full Test Suite
```bash
cd backend
.venv/bin/python -m pytest tests/ -v
# Expected: 138/138 PASSED
```

### 5. CAD Output (Phase 1 smoke test — no infrastructure needed)
```bash
cd backend
.venv/bin/python scripts/test_cad.py
# Writes 7 DXF files to output/
# Open in AutoCAD, LibreCAD, or https://sharecad.org to inspect
```

### 6. Full API — needs Docker Compose running
```bash
# Start infrastructure
cd backend
docker-compose up -d

# Run migrations
.venv/bin/python -m alembic upgrade head

# Seed database
.venv/bin/python scripts/seed_db.py

# Start API
.venv/bin/python -m uvicorn civilengineer.api.app:app --reload --port 8000

# Swagger UI (DEBUG=true required)
# http://localhost:8000/api/docs
```

Login credentials after seeding:
```
Admin:    admin@demo.civilengineer.ai  /  Admin1234!
Engineer: engineer@demo.civilengineer.ai  /  Engineer1234!
```

### 7. WebSocket — manual test (API must be running)
Connect with any WebSocket client (e.g. Postman, `wscat`):
```bash
# Get a token first via POST /api/v1/auth/login
wscat -c "ws://localhost:8000/api/v1/ws/<project_id>?token=<access_token>"
# Send:  ping
# Recv:  pong
# After uploading a plot: receives plot.analyzed event automatically
```

### 8. Plot Upload — end-to-end (API + MinIO running)
```bash
# 1. Create a project
curl -X POST http://localhost:8000/api/v1/projects/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","client_name":"Client","site_city":"Kathmandu","site_country":"NP"}'

# 2. Get presigned upload URL
curl http://localhost:8000/api/v1/projects/<project_id>/plot/upload-url \
  -H "Authorization: Bearer <token>"

# 3. Upload your DXF to the returned upload_url via PUT

# 4. Notify the server
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/plot \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"storage_key":"<key_from_step_2>","filename":"site.dxf"}'

# 5. Poll for result (or use WebSocket for push)
curl http://localhost:8000/api/v1/projects/<project_id>/plot \
  -H "Authorization: Bearer <token>"
```

### 9. Start Celery Worker (required for plot analysis in production)
```bash
cd backend
.venv/bin/python -m celery -A civilengineer.jobs.celery_app:celery_app worker \
  --loglevel=info --concurrency=2
```

---

## Infrastructure Requirements

| Service | Purpose | Docker port |
|---------|---------|-------------|
| PostgreSQL 16 | Primary database | 5432 |
| Redis 7 | Refresh tokens, Celery broker, WebSocket pub/sub | 6379 |
| MinIO | Plot DXF + design output storage | 9000 (API) / 9001 (console) |

Start all with: `docker-compose up -d` from `backend/`

---

## Phase 4 — Building Code Knowledge Base ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/schemas/rules.py` | `DesignRule`, `RuleSet`, `RuleCategory`, `Severity`, `RuleViolation`, `ComplianceReport` schemas |
| `src/civilengineer/knowledge/data/rules.json` | **63 rules** for NP-KTM (Nepal NBC 2020 / KMC Bylaw 2076) |
| `src/civilengineer/knowledge/rule_compiler.py` | Loads + validates `rules.json`; auto-generates `embedding_text` if absent |
| `src/civilengineer/knowledge/indexer.py` | ChromaDB upsert with lazy imports (no install required at runtime) |
| `src/civilengineer/knowledge/retriever.py` | `RuleRetriever` — ChromaDB vector search or keyword fallback |
| `src/civilengineer/reasoning_engine/rule_engine.py` | Deterministic compliance checker — no LLM, no hallucination |
| `scripts/index_knowledge.py` | CLI: `python scripts/index_knowledge.py [--reset] [--stats]` |
| `tests/unit/test_rule_engine.py` | 48 unit tests across 12 fixture classes |

### Rule coverage (63 rules, NP-KTM jurisdiction)

| Category | Rules | Example |
|----------|-------|---------|
| Area | 15 | Bedroom ≥ 9.5 sqm, kitchen ≥ 5 sqm, toilet ≥ 1.2 sqm |
| Setback | 8 | Front setback road-width-conditional (3–6 m), rear ≥ 1.5 m |
| Coverage | 2 | Max ground coverage 60% (hard) + 65% (soft) |
| FAR | 5 | FAR by road width: ≤1.5 (narrow), ≤2.5 (wide), ≤3.0 (arterial) |
| Height | 3 | Min floor-to-ceiling 2.75 m habitable, 2.4 m service |
| Opening | 5 | Window area ≥ 10% of floor area for habitable rooms |
| Staircase | 4 | Clear width ≥ 0.9 m, total area ≥ 4.5 sqm |
| Adjacency | 3 | Kitchen not adjacent to toilet, master bed south-of-living preferred |
| Ventilation | 2 | Cross-ventilation advisory for all habitable rooms |
| Structural | 3 | Column size, tie-beam, seismic zone advisory |
| Vastu | 8 | Kitchen SE quadrant, master bed SW, pooja NE, toilet NW (optional) |
| Accessibility | 2 | Ramp gradient ≤ 1:12, min corridor width 0.9 m |

### Rule engine logic

- **Condition filtering:** Rules are skipped if their `conditions` dict is not satisfied
  - `road_width_min/max` → skipped if no road width provided
  - `plot_area_min/max` → skipped for plots outside range
  - `num_floors_min/max` → skipped for buildings outside floor range
  - `vastu_only` → skipped when `vastu_enabled=False`
- **Violation severity:** `hard` (must fix) / `soft` (warning) / `advisory` (recommendation)
- **Output:** `ComplianceReport` with `compliant` bool, `coverage_pct`, `far_actual`, `total_built_sqm`, violation lists, `rules_checked`, `rules_skipped`

### Keyword fallback (no chromadb installed)
```python
retriever = RuleRetriever.from_rule_set(rule_set)
rules = retriever.search("minimum bedroom size Nepal")
# Returns rules with highest token overlap in embedding_text
```

### Build vector index (requires chromadb + sentence-transformers)
```bash
cd backend
uv pip install chromadb sentence-transformers
.venv/bin/python scripts/index_knowledge.py --reset
.venv/bin/python scripts/index_knowledge.py --stats
```

---

## Phase 5 — Constraint Solver + Geometry Engine ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/input_layer/validator.py` | Cross-validates `DesignRequirements` vs `PlotInfo` — FAR feasibility, room program checks |
| `src/civilengineer/input_layer/enricher.py` | Computes setbacks from rules.json + buildable zone `Rect2D` |
| `src/civilengineer/reasoning_engine/constraint_solver.py` | OR-Tools CP-SAT two-phase solver |
| `src/civilengineer/geometry_engine/layout_generator.py` | `SolveResult` → `FloorPlan` list with windows, doors, external wall flags |
| `src/civilengineer/geometry_engine/wall_builder.py` | Room bounds → `WallSegment` list; shared-wall deduplication, load-bearing detection |
| `tests/unit/test_constraint_solver.py` | 48 unit tests across 9 test classes |

### Solver design (two-phase)

**Phase A — Room sizing:**
- Looks up `min_area` and `min_dimension` from rules.json for each room type
- Applies default aspect-ratio preferences per room type
- Respects user-supplied `RoomRequirement.min_area` override
- Scales proportionally; clamps to 95% of buildable zone

**Phase B — CP-SAT placement (OR-Tools `AddNoOverlap2D`):**
- Integer-scaled coordinates (0.1 m precision = SCALE × 10)
- `NewIntervalVar` per room; `AddNoOverlap2D` prevents overlaps
- Objective: minimize bounding box (pack rooms toward origin)
- Timeout: 30s per floor; returns `PARTIAL` if some rooms can't fit

**Multi-floor distribution:**
- Ground floor: living, dining, kitchen, garage, staircase, store, pooja room
- Upper floors: bedrooms, home office
- Bathrooms distributed round-robin across all floors
- Staircase fixed to same (x, y) on every floor

**SolveStatus outcomes:**
- `SAT` — all rooms placed
- `PARTIAL` — some rooms placed; unplaced rooms listed
- `UNSAT` — no placement found (zone too small or rooms too large)
- `TIMEOUT` — solver ran out of time

### Geometry engine

**`layout_generator.py`:**
- Translates zone-relative coordinates → plot coordinates
- Detects external wall faces (room touching buildable-zone boundary)
- Adds centered `Window` (1.2 m wide) on every external face of habitable rooms
- Adds one `Door` per room (road-side preference on floor 1; internal face on upper floors)

**`wall_builder.py`:**
- Emits 4 edge segments per room (N/S/E/W)
- Deduplicates: shared edges → single `WallSegment`
- Wall thicknesses: external 350 mm, internal load-bearing 230 mm, partition 120 mm
- External walls derived from zone-boundary proximity (tolerance 20 mm)

### What is now validated
```python
result = solve_layout(requirements, buildable_zone, rules.rules)
assert result.status == SolveStatus.SAT
assert len(result.unplaced_rooms) == 0
# No overlaps:
assert not any(rooms_overlap(a, b) for a, b in combinations(result.placed_rooms, 2))
# All within zone:
assert all(pr.x + pr.width <= zone.width for pr in result.placed_rooms)

floor_plans = generate_floor_plans(result, requirements, plot_info, setbacks)
build_walls(floor_plans[0])
assert floor_plans[0].wall_segments  # walls generated
```

---

## Phase 6 — Full LangGraph Agent Loop ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/agent/state.py` | `AgentState` TypedDict — full pipeline state (all fields JSON-serialisable for checkpointing) |
| `src/civilengineer/agent/graph.py` | LangGraph `StateGraph` — 11 nodes, 5 conditional edges, 2 interrupt points |
| `src/civilengineer/agent/nodes/load_project_node.py` | Load Project + PlotInfo from DB (stub falls back gracefully) |
| `src/civilengineer/agent/nodes/validate_node.py` | Wraps `input_layer.validator` |
| `src/civilengineer/agent/nodes/plan_node.py` | Loads rules, computes buildable zone, posts strategy message |
| `src/civilengineer/agent/nodes/solve_node.py` | Wraps `constraint_solver.solve_layout()` |
| `src/civilengineer/agent/nodes/relax_node.py` | Progressive relaxation: drop optional → secondary → reduce bedrooms |
| `src/civilengineer/agent/nodes/geometry_node.py` | Wraps `layout_generator` + `wall_builder` |
| `src/civilengineer/agent/nodes/human_review_node.py` | `interrupt()` — engineer reviews floor plan before drawing |
| `src/civilengineer/agent/nodes/draw_node.py` | Per-floor DXF output via `EzdxfDriver` |
| `src/civilengineer/agent/nodes/verify_node.py` | Wraps `rule_engine.check_compliance()` |
| `src/civilengineer/agent/nodes/save_output_node.py` | Writes `compliance_report.json`; posts completion summary |
| `src/civilengineer/requirements_interview/state.py` | `InterviewState` TypedDict + phase constants |
| `src/civilengineer/requirements_interview/questions.py` | Question bank, extractor functions, adaptive gating, `answers_to_requirements()` |
| `src/civilengineer/requirements_interview/interviewer.py` | Standalone LangGraph interview subgraph (5 nodes) |
| `src/civilengineer/cli/main.py` | Typer root — `civilengineer` entry point |
| `src/civilengineer/cli/design_commands.py` | `design run`, `design resume`, `design auto`, `design history` |

### Graph topology

```
START → load_project → interview ──────────────► validate
                       (interrupt)                   │
                                           ┌─────────┴──────────┐
                                         [errors]             [ok]
                                           │                   │
                                          END                plan → solve
                                                               │     │
                                                          [UNSAT] [SAT/PARTIAL]
                                                             │        │
                                                          relax    geometry
                                                             │        │
                                                        [≤3x]     human_review
                                                          │        (interrupt)
                                                         solve     │    │    │
                                                                 [draw][solve][END]
                                                                   │
                                                                verify
                                                               │       │
                                                          [pass]    [fail→relax]
                                                            │
                                                        save_output → END
```

### Interrupt points
- **`interview`** — pauses for engineer to describe requirements (BHK config, floors, style, Vastu, special rooms)
- **`human_review`** — pauses for engineer to approve the floor plan layout before drawing

### Interview design
- Single-turn mode: engineer sends one free-text description; deterministic extractors parse it
- Full multi-turn mode: `interviewer.py` subgraph asks one question per phase (adaptive gating)
- Extractor functions: `extract_bhk`, `extract_num_floors`, `extract_style`, `extract_bool`, `extract_special_rooms`
- Adaptive gating: BHK questions skip for commercial buildings; feasibility warnings after rooms phase

### Relaxation strategy
When solver returns UNSAT, `relax_node` applies up to 3 rounds:
1. Remove optional rooms (balcony, terrace, store, corridor)
2. Remove one secondary room (home office, garage, pooja room)
3. Reduce bedroom count by 1 (warns engineer)

### CLI usage
```bash
# Non-interactive auto design (no interrupts)
.venv/bin/python -m civilengineer.cli.main design auto \
  --project demo --requirements "3BHK 2 floors modern" \
  --width 15 --depth 20 --road 7 --out output/

# Interactive design (pauses at interrupts)
.venv/bin/python -m civilengineer.cli.main design run --project demo

# Resume interrupted session
.venv/bin/python -m civilengineer.cli.main design resume <thread_id>

# List past sessions
.venv/bin/python -m civilengineer.cli.main design history
```

---

## Phase 7 — Verification Layer + Full Toolset ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/verification_layer/spatial_analyzer.py` | Adjacency graph, overlap detection, BFS circulation, Vastu zone, external-window check, adjacency constraints |
| `src/civilengineer/verification_layer/code_compliance.py` | Extended compliance: window ratio, min dimension, staircase, kitchen aspect, bathroom area, FAR, ground coverage |
| `src/civilengineer/autocad_layer/com_driver.py` | `AutoCADDriver` + `ComDocument` (win32com) + `EzdxfDocument` fallback (Linux / CI) |
| `src/civilengineer/autocad_layer/layer_manager.py` | AIA-standard layer creation via COM or ezdxf |
| `src/civilengineer/autocad_layer/transaction_manager.py` | `AutoCADTransaction` context manager with configurable retry |
| `src/civilengineer/mcp_server/server.py` | FastMCP 3.0 stdio server (`build_server()`, `open_document`, `get_active_doc`) |
| `src/civilengineer/mcp_server/tools/drawing_tools.py` | `draw_line`, `draw_polyline`, `draw_rectangle`, `draw_hatch` |
| `src/civilengineer/mcp_server/tools/element_tools.py` | `place_door`, `place_window`, `add_room_label`, `place_staircase` |
| `src/civilengineer/mcp_server/tools/annotation_tools.py` | `add_linear_dimension`, `add_text`, `add_title_block`, `add_north_arrow` |
| `src/civilengineer/mcp_server/tools/file_tools.py` | `save_drawing`, `setup_layers`, `add_custom_layer` |
| `tests/unit/test_verification_layer.py` | 66 unit tests across 10 test classes |

### Spatial analyzer capabilities

| Check | What it catches |
|-------|----------------|
| Adjacency graph | Which rooms share a wall (edge length > 5cm) |
| Overlap detection | Room pairs with non-zero intersection area |
| Circulation BFS | Required rooms unreachable from entrance |
| Vastu zone | Kitchen ≠ SE, master bed ≠ SW, pooja ≠ NE violations |
| External windows | Habitable rooms with no window on any external wall face |
| Adjacency constraints | Kitchen adj toilet, kitchen adj bathroom, living ≠ adj dining |

### Extended compliance checks (beyond rule_engine)

| Rule ID | Check | Severity |
|---------|-------|----------|
| EXT-WIN-RATIO | Window area ≥ 10% of floor area | Soft |
| EXT-MIN-DIM | No habitable room dimension < 2.1 m | Soft |
| EXT-STAIR-WIDTH | Staircase clear width ≥ 0.9 m | Hard |
| EXT-STAIR-AREA | Staircase area ≥ 4.5 sqm | Hard |
| EXT-KITCHEN-ASPECT | Kitchen aspect ratio ≤ 3:1 | Soft |
| EXT-BATH-AREA | Bathroom ≥ 1.8 sqm, toilet ≥ 0.9 sqm | Hard |
| EXT-COVERAGE-HARD | Ground coverage ≤ 60% | Hard |
| EXT-COVERAGE-SOFT | Ground coverage ≤ 65% | Soft |
| EXT-FAR | FAR ≤ road-width-conditional limit | Hard |

### AutoCAD bridge design

```
AutoCADDriver(fallback_to_dxf=True)
    .connect()          → tries win32com; silently falls back on Linux
    .open_or_new()      → ComDocument (AutoCAD) or EzdxfDocument (fallback)

AutoCADDocument (protocol)
    .add_line(start, end, layer)
    .add_polyline(points, layer, closed)
    .add_text(text, position, height, layer)
    .add_layer(name, color, linetype)
    .setup_standard_layers()    ← all AIA layers
    .save(path)                 → .dwg (COM) or .dxf (fallback)
```

### MCP server usage

```bash
# Start as standalone stdio MCP server (for Claude Desktop or agents)
python -m civilengineer.mcp_server.server

# Available tools (11 total):
#   Drawing:    draw_line, draw_polyline, draw_rectangle, draw_hatch
#   Elements:   place_door, place_window, add_room_label, place_staircase
#   Annotation: add_linear_dimension, add_text, add_title_block, add_north_arrow
#   File:       save_drawing, setup_layers, add_custom_layer
#   Session:    open_document_tool
```

---

## Phase 8 — Professional Output + Hardening ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/output_layer/cost_estimator.py` | `CostEstimator` — ₹/sqm rates × 3 grades (basic/standard/premium); structure + finishing + MEP + contingency |
| `src/civilengineer/output_layer/dxf_exporter.py` | `DXFExporter` — combined floor layout DXF, site plan DXF, floor index DXF |
| `src/civilengineer/output_layer/pdf_exporter.py` | `PDFExporter` — A4 PDF: cover + room schedule + schematic plans + compliance + cost |
| `src/civilengineer/knowledge/setback_db.py` | `SetbackDB` — 5 cities (KTM/PKR/LAL/BKT/NP-generic) × 5 road categories |
| `src/civilengineer/reasoning_engine/vastu_solver.py` | `score_vastu()`, `optimize_vastu()` — zone scoring + position-swap optimiser |
| `src/civilengineer/agent/nodes/draw_node.py` | Enhanced — per-floor DXF + combined + site plan + index + PDF + cost estimate |
| `src/civilengineer/agent/state.py` | Added `pdf_paths`, `cost_estimate` to `AgentState` |
| `tests/unit/test_phase8.py` | 72 unit tests across 8 test classes |

### Cost estimator design

| Grade | Structure (₹/sqm) | MEP factor | Contingency |
|-------|-------------------|-----------|-------------|
| basic | 12,000 | 12% | 5% |
| standard | 18,000 | 18% | 5% |
| premium | 28,000 | 25% | 5% |

Finishing rates are room-type-specific (kitchen > bathroom > bedroom > store).

### DXF export outputs (per design run)

| File | Contents |
|------|---------|
| `floor_1.dxf`, `floor_2.dxf`, … | Per-floor plan with walls, doors, windows, labels, dims |
| `combined_floors.dxf` | All floors tiled side by side (X-offset = plot_width + 3m gap) |
| `site_plan.dxf` | Plot boundary + setback lines + ground footprint + north arrow |
| `floor_index.dxf` | Cover sheet: floor count, room count, file references |

### PDF package pages

1. Cover sheet — project name, client, ID, jurisdiction, date
2. Room schedule — table: floor / room / type / width / depth / area
3. Schematic floor plans — reportlab Drawing: coloured box diagrams per floor
4. Compliance report — violations table (HARD/SOFT, rule, message, room)
5. Cost estimate — summary table + room-type breakdown (only if provided)

### Vastu optimizer

```python
vastu = score_vastu(placed_rooms, buildable_zone, facing="south")
# vastu.overall_score  0.0–1.0
# vastu.violations     ["kitchen in NW (should be SE)", …]

optimized = optimize_vastu(placed_rooms, buildable_zone)
# Swaps room positions (compatible dimensions ±20%) to improve score
```

### Setback DB cities

| Code | City | Bylaw |
|------|------|-------|
| NP-KTM | Kathmandu | KMC Bylaw 2076 |
| NP-PKR | Pokhara | PMC Bylaw 2076 |
| NP-LAL | Lalitpur/Patan | LMCB 2076 |
| NP-BKT | Bhaktapur | BMCB 2076 |
| NP | Generic Nepal | NBC 205:2020 |

---

## Architecture Layers — Completion Status

```
[0]   Project Manager      ✅ Complete (Phase 2 — project CRUD + assignments)
[0.5] Plot Analyzer        ✅ Complete (Phase 3 — DXF boundary + orientation + features)
[0.75] Requirements        ✅ Complete (Phase 6 — interview subgraph + question bank)
       Interviewer
[1]   Input Validator       ✅ Complete (Phase 5 — validator + enricher)
[2]   Reasoning Engine      ✅ Complete (Phase 4 rule engine + Phase 5 CP-SAT solver)
[3]   Geometry Engine       ✅ Complete (Phase 5 — layout generator + wall builder)
[4]   MCP Tool Server       ✅ Complete (Phase 7 — FastMCP 3.0, 11 tools, stdio transport)
[5]   AutoCAD Execution     ✅ Complete (Phase 7 — ComDocument + EzdxfDocument fallback)
[6]   Verification Layer    ✅ Complete (Phase 7 — spatial analyzer + extended compliance)
```

---

## Phase 9 — API Integration + Design Pipeline Wiring ✅

### What was built

| File | Description |
|------|-------------|
| `src/civilengineer/agent/session_store.py` | `build_persistent_graph()` with SqliteSaver; `session_to_thread_id()`, `get_graph_state()`, `get_pending_interrupt()` |
| `src/civilengineer/jobs/design_job.py` | `run_design_pipeline` Celery task — first-run + resume flows; DB update, WS event publish, interrupt detection |
| `src/civilengineer/api/routers/design.py` | 6 REST endpoints: start, list, get, interview reply, approve/reject, cancel |
| `src/civilengineer/agent/nodes/load_project_node.py` | Wired to real DB via sync SQLAlchemy (`DATABASE_URL_SYNC`); fast-path skip if state pre-populated |
| `src/civilengineer/api/app.py` | Registered design router at `/api/v1` prefix |
| `src/civilengineer/jobs/celery_app.py` | Added `civilengineer.jobs.design_job` to Celery includes |
| `tests/unit/test_phase9.py` | 60 unit tests across 8 test classes |

### Design pipeline flow (Celery + LangGraph)

```
POST /projects/{id}/design
    → Create DesignJobModel (status=pending)
    → Celery: run_design_pipeline.apply_async(...)
    → graph.invoke(initial_state, config)          ← first run
        ↓
    Graph hits interview interrupt
        → job.status = "paused", current_step = "interview"
        → Redis pub/sub: { "type": "design.paused", ... }
        → WebSocket clients notified

POST /projects/{id}/design/{session_id}/interview  { "reply": "3BHK, 2 floors" }
    → job.status = "pending" (reset)
    → Celery: run_design_pipeline(..., resume_value="3BHK, 2 floors")
    → graph.invoke(Command(resume=...), config)     ← resumes from checkpoint

    Graph hits human_review interrupt
        → job.status = "paused", current_step = "human_review"
        → floor_plan_summary included in event

POST /projects/{id}/design/{session_id}/approve    { "approved": true }
    → resume_value = "approved"
    → Pipeline continues: draw → verify → save_output
    → job.status = "completed", output_files = [...]
```

### Design API endpoints (Phase 9)

```
POST   /api/v1/projects/{project_id}/design                          Start new design job
GET    /api/v1/projects/{project_id}/design                          List all design jobs
GET    /api/v1/projects/{project_id}/design/{session_id}             Get job status + result
POST   /api/v1/projects/{project_id}/design/{session_id}/interview   Submit interview answer
POST   /api/v1/projects/{project_id}/design/{session_id}/approve     Approve / reject floor plan
DELETE /api/v1/projects/{project_id}/design/{session_id}             Cancel job
```

### Session persistence

- LangGraph graph uses **SqliteSaver** backed by `sessions/agent_sessions.db`
- Thread ID convention: `session:{session_id}` for each design session
- If `langgraph-checkpoint-sqlite` is unavailable, falls back to `MemorySaver` (no cross-process persistence)
- Each resume call (`graph.invoke(Command(resume=...), config)`) restores full pipeline state from checkpoint

### load_project_node DB wiring

- **Fast path (normal Celery flow):** Celery task pre-populates `state["project"]` before calling `graph.invoke()`; node detects this and skips the DB query entirely.
- **Slow path (direct graph invocation):** Node uses psycopg2 (sync) via `DATABASE_URL_SYNC` setting to query `ProjectModel`; returns `(project_dict, plot_info_dict, requirements_dict)`.
- **Fallback:** Any DB exception → `(None, None, None)` with warning log; node writes empty stub project dict so downstream nodes don't crash.

---

## Known Limitations / Technical Debt

| Item | Notes |
|------|-------|
| PostgreSQL RLS | Multi-tenancy currently enforced at application layer only; DB-level row security not yet applied |
| DWG (binary) support | `ezdxf.readfile()` reads DXF and some DWG formats; true binary DWG may need conversion via ODA File Converter |
| Celery retry on DB failure | `analyze_plot` retries up to 3× with 30s delay; partial DB writes not rolled back between retries |
| WebSocket auth | JWT passed as query param (browser WebSocket limitation); token expiry mid-session not handled |
| MinIO bucket creation | `ensure_bucket_exists()` must be called at startup; not yet wired into app lifespan |
| Alembic migration for PlotInfo | `plot_info` stored as JSON in existing `projects.plot_info` column — no new migration needed |
