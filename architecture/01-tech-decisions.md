# Technology Decisions (v2 — Web Portal)

All choices target a multi-user web portal deployable to cloud or on-premises.
Each decision includes rationale and what was rejected.

---

## Backend Runtime

### Python 3.12
- Latest stable, full type annotations, performance improvements
- Consistent with existing AI/solver pipeline

### uv (Package Manager)
- 10-100x faster than pip, lockfile support
- Used in backend only; frontend uses pnpm

### FastAPI (Web Framework)
- Async-native, high performance
- Native Pydantic v2 integration — request/response validation is automatic
- OpenAPI/Swagger auto-generated for frontend team
- Built-in dependency injection for auth middleware
- Reject: Django — heavy, ORM fights Pydantic; Flask — no async; Litestar — smaller community

### SQLModel (ORM)
- Pydantic + SQLAlchemy in one class definition
- No duplication between API schemas and DB models
- Alembic for migrations
- Reject: pure SQLAlchemy — verbose; pure Pydantic — no ORM; Tortoise ORM — less mature

### PostgreSQL (Primary Database)
- Multi-user concurrent access with proper isolation
- JSONB columns for flexible project properties and design rules
- Row-level security for multi-tenancy enforcement at DB level
- Alembic for schema migrations
- Reject: SQLite — no concurrent writes, single-user; MySQL — weaker JSON support

### Redis
- Job queue backend for Celery (design jobs)
- WebSocket event pub/sub (design progress updates)
- Access token revocation list (logout + token invalidation)
- Rate limiting counters
- Reject: RabbitMQ — more complex than needed; Kafka — overkill for this scale

### Celery (Async Job Queue)
- Design jobs run in background workers (solver takes 30+ seconds)
- Code extraction jobs run in background (PDF parsing)
- Multiple concurrent design sessions possible
- Job retry logic on solver failure
- Task state tracking (PENDING → STARTED → SUCCESS / FAILURE)
- Reject: RQ (Redis Queue) — simpler but less feature-complete; asyncio tasks — die with web process

---

## Frontend

### Next.js 14 (App Router) + TypeScript
- Server-side rendering for fast initial load on project dashboard
- App Router for nested layouts (sidebar + main content)
- TypeScript — type-safe API calls (generated from OpenAPI schema)
- Reject: plain React CRA — no SSR; Vite React — no SSR built-in; Vue — smaller team familiarity

### Tailwind CSS + shadcn/ui
- Utility-first CSS — fast iteration, no naming conflicts
- shadcn/ui: accessible, unstyled component primitives (Dialog, Table, Form, etc.)
- Design system that looks professional without custom CSS
- Reject: Material UI — heavy, opinionated; Chakra UI — less TypeScript-friendly

### TanStack Query (React Query)
- Server state management: fetch, cache, refetch, mutation
- Automatic stale data invalidation after mutations
- Optimistic updates for instant UI feedback
- Reject: SWR — less feature-complete; Redux Toolkit Query — heavier

### Zustand (Client State)
- Lightweight global state (user session, active project, interview state)
- Simpler than Redux for this use case
- Reject: Redux — overkill; Context API — performance issues with frequent updates

### pnpm (Frontend Package Manager)
- Faster than npm, disk-efficient with symlinks
- Consistent with monorepo workspaces setup

---

## Authentication

### python-jose + passlib + bcrypt (JWT)
- JWT access tokens (15 min expiry) + refresh tokens (7 days, httpOnly cookie)
- bcrypt for password hashing (industry standard)
- Token refresh endpoint to maintain sessions without re-login
- Reject: session cookies only — hard to scale horizontally; Auth0 — vendor lock-in for core auth

### Row-Level Security (PostgreSQL)
- Firm isolation enforced at DB level (not just application layer)
- Even if application has a bug, one firm cannot see another firm's data
- All tables include `firm_id` — RLS policy: `WHERE firm_id = current_setting('app.firm_id')`

---

## AI / LLM Layer

### LiteLLM (Model Router) — Per-Firm Configuration
- Model-agnostic: Claude, GPT-4o, Azure OpenAI, local Ollama, all via single API
- **Configuration stored in PostgreSQL `FirmSettings`** — not a config file
- Each firm provides: provider, model name, API key (encrypted), base URL
- LiteLLM reads firm settings at job start time via `get_llm_config(firm_id)`
- System-level default in `configs/llm_default.yaml` used if firm has not configured
- Reject: hardcoded model — prevents firms from choosing their preferred provider

```python
# How LLM is initialized per design job:
def get_llm_for_firm(firm_id: str) -> LiteLLM:
    firm = firm_repo.get(firm_id)
    cfg = firm.settings.llm_config or system_default_config
    return LiteLLM(
        model=cfg.model,
        api_key=decrypt(cfg.api_key),
        base_url=cfg.base_url,
        temperature=cfg.temperature,
    )
```

### LangGraph (Agent Orchestration)
- Explicit directed graph — every transition is code, not magic
- `interrupt_before` for human approval pauses (maps to WebSocket events in web version)
- `PostgresSaver` (not SqliteSaver) for distributed session persistence across workers

### sentence-transformers all-MiniLM-L6-v2 (Embeddings)
- CPU-local, no API cost, runs in Celery workers
- Consistent across jurisdictions (multilingual variant available if needed)
- For Chinese jurisdiction: switch to `paraphrase-multilingual-MiniLM-L12-v2`

---

## Building Code Extraction (New)

### PDF Parsing: pdfplumber (primary) + PyMuPDF (fallback)
- `pdfplumber`: best for text-heavy PDFs with tables (building code tables)
- `PyMuPDF (fitz)`: faster, better for scanned PDFs with embedded text
- Chunking: 500-token overlapping chunks for ChromaDB indexing
- Reject: Tesseract OCR — only needed for scanned image PDFs (rare for official codes)

### Rule Extraction: LLM-based structured output
- Firm admin uploads official building code PDF via admin portal
- Celery `code_extraction_job` chunks the PDF and prompts the LLM:
  ```
  "Extract all numeric rules (room sizes, setbacks, heights) from this text.
   Return a list of DesignRule objects with: rule_id, name, numeric_value, unit,
   severity (hard/soft/advisory), source section reference."
  ```
- LLM returns structured `DesignRule` objects via Pydantic response schema
- Extracted rules staged for human review (not auto-activated)
- Senior engineer reviews in admin UI → approves individual rules → activates
- Activated rules seeded into PostgreSQL `jurisdiction_rules` and ChromaDB

### Why not manual rules.json?
- Official building codes are hundreds of pages; manual compilation is error-prone
- LLM extraction + human review is faster, auditable, and traceable to source PDF
- When codes are updated, admin uploads new PDF and re-extracts (old versions preserved)

---

## Constraint Solving

### OR-Tools CP-SAT (Google)
- Purpose-built for geometric constraint satisfaction
- Integer variables (centimeter units internally, displayed as meters/feet)
- Per-worker instance isolation (Celery ensures no shared state)
- Multi-floor: each floor solved as linked sub-problem with staircase continuity constraints

### rectpack
- Initial room bin packing heuristic (fast starting point for CP-SAT)

### Shapely 2.x
- GEOS-backed polygon operations
- Handles irregular plots, overlap detection, setback insets
- Multi-floor: used to verify no staircase misalignment between floors

---

## CAD Generation

### ezdxf (Primary — All Deployments)
- Pure Python DXF generation — cloud-friendly, no OS dependencies
- Produces DXF R2018 format compatible with AutoCAD 2019+, BricsCAD, LibreCAD
- **Supports 3D entities**: `Mesh`, `Solid`, `3DFace`, `Polyface` for building outline
- **Elevation drawings**: generated by projecting 3D building model onto elevation planes
- PDF export via Matplotlib or ReportLab from ezdxf geometry
- Reject as sole solution: loses .dwg binary format (not needed for most use cases)

### AutoCAD COM via win32com (Optional — On-Premise Only)
- Available only when Celery worker runs on a Windows server with AutoCAD license
- Produces native .dwg files in addition to .dxf
- Enabled per-firm via `firm.settings.autocad_enabled = true`
- Planned for a later phase — not in MVP
- Reject as primary: not cloud-deployable, requires expensive per-seat licenses

### Elevation + 3D Strategy
- **Floor plan**: ezdxf 2D drawing per floor (AIA layers)
- **Elevation views**: computed from `BuildingDesign` (wall heights + roof geometry)
  projected onto orthographic planes; drawn as 2D ezdxf entities
- **3D building outline**: ezdxf 3D wireframe from `BuildingOutline3D` schema;
  exported as isometric DXF for client presentations
- **Browser preview**: SVG elevation views generated server-side from JSON geometry
  (no DXF parsing in browser)

---

## File Storage

### S3-Compatible Object Storage
- **Development / On-premise:** MinIO (self-hosted S3-compatible, Docker)
- **Production cloud:** AWS S3, Azure Blob, or GCS (provider TBD)
- Presigned URLs for direct browser upload/download (no proxy through API)
- Lifecycle policies: auto-delete temp files, archive old sessions
- Building code PDFs stored in dedicated `building-codes/` prefix
- Reject: local disk — not horizontally scalable; NFS — latency + single point of failure

---

## Knowledge Base

### ChromaDB (Vector Database)
- Per-jurisdiction collections: `rules_nepal`, `rules_india`, `rules_usa`, etc.
- Single ChromaDB instance shared across Celery workers (read-mostly)
- Collections seeded from: extracted rules + raw PDF text chunks
- Reject: Weaviate — requires separate server; Qdrant — same issue

### PostgreSQL JSONB (Structured Rules)
- Rules stored in PostgreSQL `jurisdiction_rules` table
- Source: LLM extraction from uploaded PDFs (not hand-typed JSON)
- Versioned, auditable, firm-overridable
- Firm-level rule overrides stored alongside base rules

### SQLite (Local dev only)
- Used in developer's local environment for quick iteration
- Not used in staging/production

---

## Deployment

### Docker + Docker Compose (Development)
- All services containerized: API, workers, PostgreSQL, Redis, MinIO, ChromaDB
- Single `docker-compose up` for local development
- Cloud provider to be decided — currently deploying locally only

### Kubernetes (Production — Future)
- Horizontal pod autoscaling for API + Celery workers
- StatefulSets for PostgreSQL, Redis (or use managed services)
- Secrets management via Kubernetes Secrets or HashiCorp Vault

### Nginx (Reverse Proxy)
- TLS termination
- Static file serving for Next.js build
- Rate limiting and request buffering
- WebSocket proxying for design progress

---

## Monitoring & Observability

### structlog (Logging)
- Structured JSON logs with `firm_id`, `user_id`, `project_id`, `job_id` context

### Sentry (Error Tracking)
- Frontend + backend error capture

### Prometheus + Grafana (Metrics)
- Custom metrics: solver duration, job queue depth, design success rate, by jurisdiction

### OpenTelemetry (Tracing)
- Distributed traces across API → Celery worker → subcomponents

---

## Summary Table

| Component | Choice | Key Reason |
|---|---|---|
| Python runtime | 3.12 | Latest stable |
| Backend package mgr | uv | Speed + lockfile |
| Web framework | FastAPI | Async + Pydantic native |
| ORM | SQLModel + Alembic | Pydantic + SQLAlchemy unified |
| Primary database | PostgreSQL | Multi-user, RLS, JSONB |
| Cache + queue | Redis | Job queue + pub/sub + rate limiting |
| Background jobs | Celery | Async solver + code extraction jobs |
| LLM routing | LiteLLM | Model-agnostic, per-firm config from DB |
| Agent orchestration | LangGraph | Explicit graph + HiTL |
| Checkpointing | LangGraph PostgresSaver | Distributed workers |
| Constraint solver | OR-Tools CP-SAT | Geometric CSP, multi-floor |
| Vector DB | ChromaDB | Local, per-jurisdiction collections |
| Embeddings | sentence-transformers | CPU-local, zero cost |
| Data validation | Pydantic v2 | Validation + ORM + API schemas |
| PDF parsing | pdfplumber + PyMuPDF | Building code rule extraction |
| CAD primary | ezdxf | Cloud-friendly, 3D support, no licenses |
| CAD optional | AutoCAD COM | On-prem .dwg (future phase) |
| Elevation rendering | ezdxf 3D projection | Floor plan + elevations + 3D outline |
| File storage | S3-compatible (MinIO/cloud TBD) | Scalable, presigned URLs |
| Frontend framework | Next.js 14 + TypeScript | SSR + type safety |
| CSS | Tailwind + shadcn/ui | Fast iteration, accessible |
| Server state | TanStack Query | Caching + mutations |
| Client state | Zustand | Lightweight |
| Frontend pkg mgr | pnpm | Speed + monorepo |
| Auth | JWT + bcrypt (python-jose) | Standard, no vendor lock-in |
| Container | Docker Compose (dev) | Simple local setup |
| Reverse proxy | Nginx | TLS, WebSocket, rate limiting |
| Error tracking | Sentry | Frontend + backend |
| Metrics | Prometheus + Grafana | Standard observability stack |
| Tracing | OpenTelemetry | Distributed traces |
