# Frontend Architecture (Next.js 14)

## Overview

A server-side rendered web application using the Next.js App Router. Engineers
access the system from any browser — no desktop software required. The UI
provides a project dashboard, conversational interview, floor plan viewer, and
design history.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Framework | Next.js 14 (App Router) + TypeScript |
| Styling | Tailwind CSS + shadcn/ui |
| Server state | TanStack Query (React Query v5) |
| Client state | Zustand |
| Forms | React Hook Form + Zod |
| Charts/data | Recharts |
| Floor plan SVG | Custom renderer (dxf-renderer.ts) |
| API types | Auto-generated from OpenAPI (scripts/generate_api_types.py) |
| Package manager | pnpm |

---

## Application Structure

### Route Groups

```
(auth)/          — Unauthenticated pages (login, forgot password)
(portal)/        — Authenticated pages with sidebar layout
(portal)/admin/  — firm_admin only section
```

### Page Map

```
/login                              → Login form
/forgot-password                    → Password reset request

/dashboard                          → Project list (default after login)
/projects/new                       → Create project wizard (3 steps)
/projects/[id]                      → Project overview card
/projects/[id]/plot                 → Upload plot DWG + review extraction
/projects/[id]/interview            → Requirements interview chat
/projects/[id]/design               → Design sessions list
/projects/[id]/design/[sessionId]   → Design session detail + progress
/projects/[id]/design/[sessionId]/review  → Floor plan approval UI
/projects/[id]/files                → Download output files

/settings                           → User profile, password change

/admin/users                        → User management (firm_admin)
/admin/settings                     → Firm settings, jurisdiction config
```

---

## Key Components

### `ProjectCard.tsx`
Displays project thumbnail with status badge, latest session info,
jurisdiction flag, and quick-action buttons (continue, view history).

### `PlotUpload.tsx`
Drag-and-drop DWG/DXF upload component:
1. Validates file extension (.dwg, .dxf)
2. Gets presigned S3 upload URL from API
3. Uploads directly to S3 with progress bar
4. Notifies API on completion → triggers plot analysis job
5. Shows analysis results with confidence indicator

### `PlotPreview.tsx`
SVG visualization of the extracted plot polygon. Shows:
- Plot boundary (blue outline)
- North arrow
- Dimension annotations (width × depth)
- Facing direction label
- Site features (trees, roads as icons)
- Extraction confidence badge (green ≥ 0.8, yellow ≥ 0.6, red < 0.6)

### `InterviewChat.tsx`
Conversational interview UI:
- Chat-style message bubbles (AI on left, engineer on right)
- Dynamic input area: text field, multi-choice buttons, number input (based on `input_type`)
- Each phase shows a progress step indicator at top
- Engineer can scroll back to review previous answers
- "Edit answer" button on any previous turn restarts from that phase

### `DesignProgress.tsx`
Real-time progress display for running design jobs:
- Step timeline with checkmarks (solved steps) and spinner (current)
- Step labels: Loading → Planning → Solving → Geometry → **Elevations** → Reviewing → Drawing → Verifying
- "Awaiting Approval" banner appears when elevation generation completes
- Shows floors solved (e.g. "Floor 2 of 3 complete")
- WebSocket subscription to `design.progress` events

### `FloorPlanViewer.tsx`
2D SVG floor plan viewer (multi-floor):
- Tab bar to switch between floors (Floor 1 / Floor 2 / Floor 3)
- Renders `FloorPlan` JSON as SVG (not DXF — browser-native)
- Color-coded rooms by type (bedroom=blue, kitchen=orange, bathroom=teal, etc.)
- Room labels with name + area
- Wall thickness visualization
- Staircase highlighted across floors (shows continuity)
- North arrow
- Hover: shows room details panel
- Zoom + pan (SVG transform)
- "Approve" and "Request Changes" buttons below
- Compliance indicators: green check (passes rule), amber warning (soft rule relaxed), red (issue)

### `ElevationViewer.tsx`
Elevation drawing viewer (new):
- Four-tab layout: Front / Rear / Left / Right
- SVG rendering of `ElevationView` JSON:
  - Wall outline with floor band lines
  - Window and door openings at correct positions
  - Roof outline (flat/gable/terrace)
  - Floor height annotations
  - Parapet if present
- North direction label on each face (e.g. "FRONT (NORTH)")
- Zoom + pan
- Shown alongside floor plan in approval UI

### `Building3DViewer.tsx`
3D isometric building outline (new):
- SVG isometric projection from `BuildingOutline3D` JSON
- Wireframe style: footprint extruded to floor heights with roof outline
- Rotate between isometric angles (SE / SW / NE / NW view)
- Used for client presentation and quick gestalt check
- Not interactive detail view — just building massing

### `ComplianceReport.tsx`
Post-design compliance summary:
- Grouped by jurisdiction (NBC Nepal / seismic zone / local bylaws)
- Pass/fail/warning per rule — links to source PDF section
- Design rationale (LLM explanation)
- Constraints relaxed during solving (with explanation)
- Download compliance PDF button

### `LLMConfigForm.tsx` (admin — new)
Firm LLM configuration form on `/admin/llm-config`:
- Provider dropdown: Anthropic / OpenAI / Azure OpenAI / Ollama / Custom
- Model name text input (with common model suggestions per provider)
- API key input (password field, shows only last 4 chars if already set)
- Base URL input (shown only for Azure / Ollama / Custom)
- Temperature slider (0.0 – 1.0, default 0.3)
- "Test Connection" button → calls `/admin/llm-config/test` → shows latency + success
- "Save" button
- "Using system default" badge if no firm config is set
- Security note: "Your API key is encrypted and never transmitted back to this page"

### `BuildingCodeUpload.tsx` (admin — new)
Building code PDF management on `/admin/building-codes`:
- Table of all uploaded code documents with: name, jurisdiction, status, rules count
- "Upload Building Code" button → modal with:
  - Jurisdiction selector
  - Code name + version fields
  - Drag-and-drop PDF upload (progress bar, 100MB max)
- Per-document actions: Extract Rules / View Rules / Activate / Delete
- Status badges: Uploaded / Extracting (spinner) / Needs Review / Active / Superseded

### `RuleReviewTable.tsx` (admin — new)
Rule review interface on `/admin/building-codes/{id}/review`:
- Table of all extracted rules with columns:
  - Source section + page number
  - Proposed rule ID
  - Category + severity (editable dropdown)
  - Numeric value + unit (editable)
  - Confidence score (color-coded bar: green ≥ 0.85, amber ≥ 0.60, red < 0.60)
  - Source text (expandable verbatim PDF text)
  - Approve ✓ / Reject ✗ buttons
- Filter by: confidence range, category, pending review
- "Approve All High Confidence" bulk action (confidence ≥ 0.85)
- "Activate X Approved Rules" button at bottom

---

## State Management

### Zustand Store

```typescript
interface AppStore {
  // Auth
  user: User | null;
  firm: Firm | null;
  setUser: (user: User | null) => void;

  // Active context
  activeProjectId: string | null;
  setActiveProject: (id: string | null) => void;

  // Interview
  interviewId: string | null;
  setInterviewId: (id: string | null) => void;

  // Design job
  activeJobId: string | null;
  jobProgress: JobProgress | null;
  approvalRequest: ApprovalRequest | null;
  setJobProgress: (p: JobProgress) => void;
  setApprovalRequest: (a: ApprovalRequest | null) => void;
}
```

### TanStack Query Keys

```typescript
const queryKeys = {
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  plotInfo: (id: string) => ['projects', id, 'plot'] as const,
  requirements: (id: string) => ['projects', id, 'requirements'] as const,
  designs: (id: string) => ['projects', id, 'designs'] as const,
  design: (id: string, sessionId: string) => ['projects', id, 'designs', sessionId] as const,
  jobStatus: (jobId: string) => ['jobs', jobId] as const,
}
```

---

## WebSocket Integration

```typescript
// src/hooks/useDesignJob.ts

export function useDesignJob(jobId: string) {
  const setJobProgress = useAppStore(s => s.setJobProgress);
  const setApprovalRequest = useAppStore(s => s.setApprovalRequest);
  const queryClient = useQueryClient();

  useEffect(() => {
    const ws = createWebSocket(jobId); // src/lib/websocket.ts

    ws.on('design.progress', (data: JobProgress) => {
      setJobProgress(data);
    });

    ws.on('design.approval_required', (data: ApprovalRequest) => {
      setApprovalRequest(data);
      // Navigate to review page
    });

    ws.on('design.completed', (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.designs(data.project_id) });
    });

    ws.on('plot.analyzed', (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.plotInfo(data.project_id) });
    });

    return () => ws.close();
  }, [jobId]);
}
```

---

## Floor Plan SVG Renderer

The `dxf-renderer.ts` module converts `FloorPlan` JSON (not DXF) to SVG.
It does NOT parse DXF files in the browser — that would be complex and slow.

```typescript
// src/lib/dxf-renderer.ts

interface RenderOptions {
  width: number;        // SVG viewport width in pixels
  height: number;
  showDimensions: boolean;
  showNorthArrow: boolean;
  colorByRoomType: boolean;
  highlightIssues: boolean;
}

const ROOM_COLORS: Record<RoomType, string> = {
  bedroom: '#93C5FD',           // Blue-300
  master_bedroom: '#3B82F6',    // Blue-500
  living_room: '#86EFAC',       // Green-300
  kitchen: '#FCD34D',           // Amber-300
  bathroom: '#67E8F9',          // Cyan-300
  staircase: '#D1D5DB',         // Gray-300
  // ...
};

export function renderFloorPlan(floorPlan: FloorPlan, options: RenderOptions): string {
  // Returns SVG string
  // Scale: feet → pixels using viewport size and plot dimensions
  // Rooms: filled rects with room color + label
  // Walls: strokes with thickness
  // Doors: arc symbols
  // Windows: dashed lines on walls
}
```

---

## Create Project Wizard (3 Steps)

```
Step 1 — Basic Info
  Project name, client name, site address, city, country
  → Country selection auto-suggests jurisdiction (Nepal → NP-KTM default)

Step 2 — Jurisdiction + Building
  Jurisdiction dropdown (filtered by selected country)
  For Nepal: road width input (determines setback automatically)
  Number of floors (1–10, affects solver complexity estimate)
  Local body input (KMC / PMC / Municipal)
  Shows: "This project will follow NBC 2020 with KMC Bylaws 2079"
  Preview: computed setbacks based on road width (Nepal) or jurisdiction defaults
  FAR/max coverage preview

Step 3 — Options
  Units preference (feet / meters) — default per jurisdiction
  CAD output format (DXF only for cloud; DWG if firm has on-prem license)
  Style options: Vastu (India), Feng Shui (China), Traditional Newari (Nepal)
  Seismic zone: auto-detected from jurisdiction, override if needed
  Initial engineers to assign (optional)

→ Create Project → Redirect to /projects/[id]/plot
```

---

## Accessibility

The UI follows WCAG 2.1 AA:
- All interactive elements keyboard-accessible
- Screen reader labels on all form fields and icon buttons
- Color is not the sole indicator (icons + text alongside color badges)
- shadcn/ui components are built on Radix UI (accessible primitives)
- Focus management: dialogs trap focus, modals restore focus on close

---

## Internationalization (Future)

The frontend is structured for i18n (but English-only in v1):
- All strings in `messages/en.json`
- `next-intl` library ready to add
- RTL layout support via Tailwind's `rtl:` prefix
- Indian languages (Hindi) and Chinese (Simplified) prioritized for v2

---

## Performance Targets

| Metric | Target |
|--------|--------|
| First Contentful Paint | < 1.5s |
| Time to Interactive | < 3.0s |
| Lighthouse Score | ≥ 90 |
| Bundle size (initial) | < 200 KB gzipped |
| Floor plan SVG render | < 100ms for typical floor plan |
