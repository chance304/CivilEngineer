# REST API Design

## Base URL
```
/api/v1/
```

All endpoints require `Authorization: Bearer <token>` unless marked **[public]**.
All responses use `Content-Type: application/json`.
Errors follow RFC 7807 (Problem Details).

---

## Authentication Endpoints

```
POST   /api/v1/auth/login              [public] Login with email + password
POST   /api/v1/auth/refresh            [public] Refresh access token via cookie
DELETE /api/v1/auth/logout                      Invalidate session
POST   /api/v1/auth/forgot-password    [public] Send password reset email
POST   /api/v1/auth/reset-password     [public] Reset password with token
GET    /api/v1/auth/google             [public] Google OAuth redirect
GET    /api/v1/auth/google/callback    [public] Google OAuth callback
```

---

## User Endpoints

```
GET    /api/v1/users/me                         Current user profile
PUT    /api/v1/users/me                         Update name, password

# firm_admin only:
GET    /api/v1/users                            List firm users
POST   /api/v1/users                            Invite user (sends email)
GET    /api/v1/users/{user_id}                  Get user
PUT    /api/v1/users/{user_id}                  Update role, deactivate
DELETE /api/v1/users/{user_id}                  Deactivate user
```

---

## Firm Endpoints

```
GET    /api/v1/firm                             Get firm details
PUT    /api/v1/firm/settings                    Update firm settings (firm_admin)
GET    /api/v1/firm/stats                       Projects, active jobs, usage stats
```

---

## Project Endpoints

```
GET    /api/v1/projects                         List projects (filtered by role)
POST   /api/v1/projects                         Create project
GET    /api/v1/projects/{project_id}            Get project
PUT    /api/v1/projects/{project_id}            Update metadata
DELETE /api/v1/projects/{project_id}            Archive project

GET    /api/v1/projects/{project_id}/properties Get project properties (jurisdiction config)
PUT    /api/v1/projects/{project_id}/properties Update project properties

# Assignments
GET    /api/v1/projects/{project_id}/engineers  List assigned engineers
POST   /api/v1/projects/{project_id}/engineers  Assign engineer
DELETE /api/v1/projects/{project_id}/engineers/{user_id}  Remove assignment
```

### Create Project Request Body

```json
{
  "name": "Thapa Residence",
  "client_name": "Mr. Bikash Thapa",
  "site_address": "Plot 12, Baneshwor",
  "site_city": "Kathmandu",
  "site_country": "NP",
  "properties": {
    "jurisdiction": "NP-KTM",
    "jurisdiction_version": "NBC_2020_KTM",
    "local_body": "KMC",
    "road_width_m": 6.0,
    "num_floors": 3,
    "dimension_units": "meters"
  }
}
```

### Project Properties Response

```json
{
  "jurisdiction": "NP-KTM",
  "jurisdiction_version": "NBC_2020_KTM",
  "jurisdiction_display": "Nepal — Kathmandu Valley (NBC 2020 + KMC Bylaws 2079)",
  "local_body": "KMC",
  "road_width_m": 6.0,
  "setbacks": {
    "front_m": 3.0,
    "rear_m": 1.5,
    "left_m": 1.5,
    "right_m": 1.5,
    "source": "NBCR 2072 — road width 6m requires 3m front setback"
  },
  "far_limits": {
    "max_far": 2.0,
    "max_coverage_pct": 70.0,
    "source": "KMC Bylaws 2079, Residential Zone"
  },
  "num_floors": 3,
  "seismic_zone": "V",
  "dimension_units": "meters",
  "custom_overrides": {}
}
```

---

## Plot Endpoints

```
POST   /api/v1/projects/{project_id}/plot       Upload + analyze plot DWG
GET    /api/v1/projects/{project_id}/plot        Get plot analysis results
GET    /api/v1/projects/{project_id}/plot/upload-url  Get presigned S3 URL for direct upload
```

### Plot Upload Flow

```
1. Client calls:
   GET /api/v1/projects/{id}/plot/upload-url
   Response: { "upload_url": "https://s3.../...", "fields": {...}, "key": "plots/..." }

2. Client uploads file directly to S3 (no API proxy):
   POST {upload_url} with multipart form data

3. Client notifies API:
   POST /api/v1/projects/{id}/plot
   Body: { "storage_key": "plots/...", "filename": "site_plot.dwg" }

4. API queues a plot analysis job (Celery)
   Response: { "job_id": "job_abc", "status": "pending" }

5. Client subscribes to WebSocket for plot.analyzed event
   Or polls: GET /api/v1/projects/{id}/plot (until status != "analyzing")
```

### Plot Analysis Response

```json
{
  "status": "analyzed",
  "confidence": 0.95,
  "plot_info": {
    "area_sqft": 2400.0,
    "width_ft": 40.0,
    "depth_ft": 60.0,
    "is_rectangular": true,
    "facing": "north",
    "north_direction_deg": 0.0,
    "existing_features": ["road_north"],
    "extraction_notes": []
  },
  "polygon_svg": "<svg>...</svg>"
}
```

---

## Interview Endpoints

```
POST   /api/v1/projects/{project_id}/interviews         Start new interview
GET    /api/v1/projects/{project_id}/interviews/{id}    Get interview state
POST   /api/v1/projects/{project_id}/interviews/{id}/answer  Submit an answer
PUT    /api/v1/projects/{project_id}/interviews/{id}/confirm Confirm requirements
GET    /api/v1/projects/{project_id}/requirements        Get confirmed requirements
```

### Interview Answer Flow

```
POST /api/v1/projects/{id}/interviews
Response:
{
  "interview_id": "int_abc",
  "phase": "greeting",
  "message": "Welcome! Your plot is 2,400 sqft, north facing in Pune, Maharashtra.
              Let's define your building requirements.
              What type of building is this?",
  "options": ["Residential", "Commercial", "Mixed-use"],
  "input_type": "choice"
}

POST /api/v1/projects/{id}/interviews/int_abc/answer
Body: { "answer": "Residential" }
Response:
{
  "phase": "scale",
  "message": "How many floors do you want?",
  "input_type": "number",
  "validation": { "min": 1, "max": 5 }
}

... (continues until phase = "confirmation")

PUT /api/v1/projects/{id}/interviews/int_abc/confirm
Body: { "confirmed": true }
Response: { "status": "confirmed", "requirements": { ... } }
```

---

## Design Job Endpoints

```
POST   /api/v1/projects/{project_id}/designs            Submit design job
GET    /api/v1/projects/{project_id}/designs            List design sessions
GET    /api/v1/projects/{project_id}/designs/{session_id}  Get session detail
GET    /api/v1/projects/{project_id}/designs/{session_id}/status  Get job status
POST   /api/v1/projects/{project_id}/designs/{session_id}/approve  Approve floor plan
DELETE /api/v1/projects/{project_id}/designs/{session_id}  Cancel running job
```

### Submit Design Job

```
POST /api/v1/projects/{project_id}/designs
Body: { "requirements_override": null }   (null = use saved requirements)

Response:
{
  "job_id": "job_xyz",
  "session_id": "sess_abc",
  "status": "pending",
  "queue_position": 2,
  "estimated_start_seconds": 30
}
```

### Design Job Status

```
GET /api/v1/projects/{id}/designs/{session_id}/status

{
  "job_id": "job_xyz",
  "status": "running",
  "current_step": "elevation",
  "step_message": "Generating elevation views and 3D building outline...",
  "progress_pct": 72,
  "solver_iteration": null,
  "elapsed_seconds": 51,
  "floors_solved": 3
}
```

Pipeline steps in order:
`loading → planning → solving → geometry → elevation → awaiting_approval → drawing → verifying → saving → done`

### Approve Floor Plan (After AWAITING_APPROVAL Pause)

```
POST /api/v1/projects/{id}/designs/{session_id}/approve
Body:
{
  "approved": true,
  "feedback": null
}
OR
{
  "approved": false,
  "feedback": "Move master bedroom to southwest corner"
}
```

---

## File Download Endpoints

```
GET    /api/v1/projects/{project_id}/designs/{session_id}/files           List output files
GET    /api/v1/projects/{project_id}/designs/{session_id}/files/{key}/url Get presigned download URL
```

### File List Response

```json
{
  "session_id": "sess_abc",
  "files": [
    { "key": "floor_plan_F1.dxf",       "type": "floor_plan",   "floor": 1,   "size_bytes": 87340 },
    { "key": "floor_plan_F2.dxf",       "type": "floor_plan",   "floor": 2,   "size_bytes": 82100 },
    { "key": "floor_plan_F3.dxf",       "type": "floor_plan",   "floor": 3,   "size_bytes": 79800 },
    { "key": "elevation_front.dxf",     "type": "elevation",    "face": "front",  "size_bytes": 34200 },
    { "key": "elevation_rear.dxf",      "type": "elevation",    "face": "rear",   "size_bytes": 33100 },
    { "key": "elevation_left.dxf",      "type": "elevation",    "face": "left",   "size_bytes": 31500 },
    { "key": "elevation_right.dxf",     "type": "elevation",    "face": "right",  "size_bytes": 30900 },
    { "key": "building_3d.dxf",         "type": "3d_outline",   "size_bytes": 56200 },
    { "key": "full_set.pdf",            "type": "pdf_set",      "size_bytes": 1245890 },
    { "key": "report.json",             "type": "report",       "size_bytes": 12300 }
  ],
  "generated_at": "2025-02-18T14:30:00Z"
}
```

---

## Admin Endpoints (firm_admin only)

### LLM Configuration

```
GET    /api/v1/admin/llm-config                  Get firm's current LLM config
PUT    /api/v1/admin/llm-config                  Set LLM provider + model + API key
POST   /api/v1/admin/llm-config/test             Test connection with current config
DELETE /api/v1/admin/llm-config                  Remove config (revert to system default)
```

#### GET /api/v1/admin/llm-config Response
```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "api_key_set": true,
  "api_key_last4": "a7f2",
  "base_url": null,
  "temperature": 0.3,
  "using_system_default": false
}
```
Note: `api_key` is never returned in full — only whether it's set and last 4 chars.

#### PUT /api/v1/admin/llm-config Request Body
```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "api_key": "sk-...",
  "base_url": null,
  "temperature": 0.3
}
```

#### POST /api/v1/admin/llm-config/test Response
```json
{
  "success": true,
  "model": "gpt-4o",
  "latency_ms": 423,
  "message": "Connection successful. Model responded correctly."
}
```

---

### Building Code Management

```
# Upload + manage building code PDFs
GET    /api/v1/admin/building-codes                          List all uploaded code documents
POST   /api/v1/admin/building-codes/upload-url              Get presigned S3 URL for PDF upload
POST   /api/v1/admin/building-codes                         Notify API of upload + create record
POST   /api/v1/admin/building-codes/{doc_id}/extract        Queue LLM extraction job
GET    /api/v1/admin/building-codes/{doc_id}                Get document + extraction status
GET    /api/v1/admin/building-codes/{doc_id}/rules          List extracted rules (for review)
PUT    /api/v1/admin/building-codes/{doc_id}/rules/{rule_id} Approve/reject/edit one rule
POST   /api/v1/admin/building-codes/{doc_id}/activate       Activate all approved rules
DELETE /api/v1/admin/building-codes/{doc_id}                Delete document (if not active)
```

#### Building Code Upload Flow

```
1. GET /api/v1/admin/building-codes/upload-url
   Response: { "upload_url": "...", "key": "building-codes/firm_x/doc_abc/nbc_205.pdf" }

2. Client uploads PDF directly to S3

3. POST /api/v1/admin/building-codes
   Body: {
     "s3_key": "building-codes/firm_x/doc_abc/nbc_205.pdf",
     "jurisdiction": "NP-KTM",
     "code_name": "NBC 205:2012 — Mandatory Rules of Thumb",
     "code_version": "NBC_205_2012"
   }
   Response: { "doc_id": "doc_abc", "status": "uploaded" }

4. POST /api/v1/admin/building-codes/doc_abc/extract
   Response: { "extraction_job_id": "job_ext_123", "status": "extracting" }
   (WebSocket: building_code.extraction_complete when done)

5. GET /api/v1/admin/building-codes/doc_abc/rules
   Response: list of ExtractedRule objects with confidence scores

6. PUT /api/v1/admin/building-codes/doc_abc/rules/exr_001
   Body: { "approved": true, "notes": "Verified against Section 4.2" }

7. POST /api/v1/admin/building-codes/doc_abc/activate
   → Copies approved rules to jurisdiction_rules
   → Triggers ChromaDB rebuild for jurisdiction
   → doc status = "active"
```

#### Extracted Rules List Response

```json
{
  "doc_id": "doc_abc",
  "code_name": "NBC 205:2012 — Mandatory Rules of Thumb",
  "rules_total": 28,
  "rules_approved": 12,
  "rules_rejected": 2,
  "rules_pending": 14,
  "rules": [
    {
      "extracted_rule_id": "exr_001",
      "proposed_rule_id": "NP_NBC205_4.2.1",
      "name": "Minimum bedroom area",
      "numeric_value": 7.0,
      "unit": "sqm",
      "severity": "hard",
      "source_section": "NBC 205:2012, Section 4.2, Table 4.1",
      "source_page": 18,
      "source_text": "The minimum floor area of a bedroom shall not be less than 7.0 sq.m...",
      "confidence": 0.96,
      "reviewer_approved": null
    }
  ]
}
```

---

### Jurisdiction Rule Overrides

```
GET    /api/v1/admin/jurisdiction-rules          List all active rules for firm's jurisdiction
PUT    /api/v1/admin/jurisdiction-rules/{rule_id} Override a rule value for this firm
DELETE /api/v1/admin/jurisdiction-rules/{rule_id}/override  Remove override
GET    /api/v1/admin/audit-log                   Recent actions in the firm
```

---

## WebSocket Events

Connect to: `ws://{host}/api/v1/ws?token=<access_token>`

### Events sent by server to client

```json
// Design job progress
{
  "event": "design.progress",
  "data": {
    "job_id": "job_xyz",
    "session_id": "sess_abc",
    "status": "running",
    "current_step": "solving",
    "progress_pct": 45,
    "step_message": "Running constraint solver..."
  }
}

// Human approval required
{
  "event": "design.approval_required",
  "data": {
    "job_id": "job_xyz",
    "session_id": "sess_abc",
    "floor_plan_summary": { ... },
    "compliance_preview": { ... }
  }
}

// Design complete — includes all floor plans + elevations + 3D
{
  "event": "design.completed",
  "data": {
    "session_id": "sess_abc",
    "project_id": "prj_abc",
    "output_files": [
      "floor_plan_F1.dxf", "floor_plan_F2.dxf", "floor_plan_F3.dxf",
      "elevation_front.dxf", "elevation_rear.dxf",
      "elevation_left.dxf", "elevation_right.dxf",
      "building_3d.dxf", "full_set.pdf", "report.json"
    ],
    "floors_completed": 3
  }
}

// Design failed
{
  "event": "design.failed",
  "data": {
    "session_id": "sess_abc",
    "error": "Design impossible: Plot too small for 3BHK under NBC 2016"
  }
}

// Plot analysis complete
{
  "event": "plot.analyzed",
  "data": {
    "project_id": "prj_abc",
    "confidence": 0.95,
    "plot_info": { ... }
  }
}

// Building code extraction complete (admin channel only)
{
  "event": "building_code.extraction_complete",
  "data": {
    "doc_id": "doc_abc",
    "jurisdiction": "NP-KTM",
    "rules_extracted": 28,
    "high_confidence": 21,
    "needs_review": 7
  }
}

// Building code activated (broadcast to all firm connections)
{
  "event": "building_code.activated",
  "data": {
    "doc_id": "doc_abc",
    "jurisdiction": "NP-KTM",
    "rules_activated": 26,
    "knowledge_base_rebuilt": true
  }
}
```

---

## Standard Error Responses

```json
// 400 Bad Request
{
  "type": "https://civilengineer.app/errors/validation-error",
  "title": "Validation Error",
  "status": 400,
  "detail": "jurisdiction must be a valid jurisdiction code",
  "instance": "/api/v1/projects"
}

// 401 Unauthorized
{
  "type": "https://civilengineer.app/errors/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Access token expired or invalid"
}

// 403 Forbidden
{
  "type": "https://civilengineer.app/errors/forbidden",
  "title": "Forbidden",
  "status": 403,
  "detail": "You do not have permission to perform this action"
}

// 404 Not Found
{
  "type": "https://civilengineer.app/errors/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "Project prj_abc123 not found"
}

// 409 Conflict
{
  "type": "https://civilengineer.app/errors/design-already-running",
  "title": "Design Job Already Running",
  "status": 409,
  "detail": "A design job is already running for this project. Cancel it or wait for completion."
}

// 422 Design Impossible
{
  "type": "https://civilengineer.app/errors/design-impossible",
  "title": "Design Not Feasible",
  "status": 422,
  "detail": "Your 3BHK program requires at least 2,450 sqft. Your plot allows 2,100 sqft under NBC 2016 FAR. Suggestions: (1) Reduce to 2BHK, (2) Add a second floor, (3) Request FAR variance."
}
```

---

## API Versioning Strategy

URL-based versioning: `/api/v1/`, `/api/v2/`

- Maintain at least one previous version for 12 months after deprecation
- Breaking changes → new version
- Additive changes (new fields) → same version, documented in changelog
- Frontend fetches version from `GET /api/health` and shows deprecation warnings
