# LangGraph Agent Graph (Orchestration) v2

## Overview

LangGraph is the orchestration layer that wires all pipeline layers together into a
stateful directed graph. In v2, the entire graph runs inside a **Celery background job**
(`jobs/design_job.py`). Human approval pauses send **WebSocket events** to the browser
instead of blocking a CLI session.

## Execution Context

```
Browser (engineer)
    │  POST /api/v1/projects/{id}/designs
    ▼
FastAPI API
    │  Creates DesignJob record in PostgreSQL
    │  Queues Celery task
    ▼
Celery Worker (design queue)
    │  Picks up task
    │  Runs LangGraph agent graph
    │  On AWAITING_APPROVAL → publishes event to Redis pub/sub
    │                          → WebSocket delivers to browser
    │  Browser POSTs approval → Redis → worker resumes
    ▼
LangGraph PostgresSaver (replaces SqliteSaver)
    │  Checkpoints at each node
    │  Allows resume if worker crashes
    ▼
Output: DXF + PDF written to S3
```

## Checkpointer: PostgresSaver (Not SqliteSaver)

Multiple workers need shared access to session state. `SqliteSaver` is local-only.
`PostgresSaver` (official LangGraph PostgreSQL checkpointer) stores state in the
same PostgreSQL database, accessible by any worker.

---

## Human Approval: WebSocket Not CLI

The `approval_pause_node` (renamed from `human_review_node`) does NOT block the
Celery worker. Instead:
1. Node publishes `design.approval_required` event to Redis pub/sub
2. Node exits — worker thread is freed
3. Browser receives event via WebSocket → shows floor plan preview + buttons
4. Engineer clicks Approve/Request Changes → POST to `/api/v1/projects/{id}/designs/{sessionId}/approve`
5. API writes approval to Redis key `approval:{job_id}`
6. Worker polls Redis for approval (non-blocking, 1s intervals, timeout 24h)
7. Worker reads approval, updates state, continues graph

## Agent State

All data flows through a single `AgentState`. Nodes read from it and return
updates (LangGraph merges updates into the state).
The `job_id` and `firm_id` fields are added for v2 (not present in v1).

```python
class AgentState(TypedDict):
    # ── Project context ────────────────────────────────────────────────
    project_id: str
    session_id: str
    firm_id: str                         # For LLM config loading
    job_id: str                          # Celery job ID (v2)
    project: Optional[Project]           # Loaded by load_project_node
    plot_info: Optional[PlotInfo]        # From project.plot_info

    # ── Requirements ───────────────────────────────────────────────────
    requirements: Optional[DesignRequirements]  # Set by interview_node
    requirements_confirmed: bool         # True after engineer confirms
    num_floors: int                      # From requirements — drives multi-floor solve

    # ── Reasoning ─────────────────────────────────────────────────────
    retrieved_rules: Optional[RuleSet]
    design_strategy: Optional[DesignStrategy]   # LLM qualitative output
    solver_iterations: int
    solver_status: str                   # "sat" | "unsat" | "pending"
    relaxed_constraints: list[str]       # Rule IDs relaxed during UNSAT loop

    # ── Geometry (multi-floor) ─────────────────────────────────────────
    floor_plans: list[FloorPlan]         # One per floor, indexed by floor number
    building_design: Optional[BuildingDesign]   # Container for all floors

    # ── Elevation + 3D (new) ──────────────────────────────────────────
    elevation_set: Optional[ElevationSet]   # Front/rear/left/right + 3D outline
    elevation_complete: bool

    # ── CAD Drawing ───────────────────────────────────────────────────
    mcp_tool_log: list[dict]             # All tool calls + results (for debugging)
    drawing_complete: bool

    # ── Verification ──────────────────────────────────────────────────
    verification_passed: bool
    verification_issues: list[str]       # Hard violations
    verification_warnings: list[str]     # Soft advisories
    revision_count: int

    # ── Human-in-the-loop ─────────────────────────────────────────────
    human_feedback: Optional[str]        # Set when engineer provides input

    # ── Output ────────────────────────────────────────────────────────
    output_files: list[str]              # S3 keys of generated files
    error: Optional[str]                 # Terminal error message

    # ── Conversation (for LLM nodes) ─────────────────────────────────
    messages: Annotated[list, add_messages]
```

---

## Graph Structure

```
START
  │
  ▼
load_project_node
  │  Loads Project + PlotInfo from PostgreSQL.
  │  Loads firm's LLM config (or system default).
  │  Checks if requirements already saved (skip interview option).
  ▼
interview_node          ←──────────────────────────────────────────┐
  │  Launches requirements_interview subgraph.                      │
  │  interrupt_before: pause for engineer Q&A                       │
  │  Output: requirements, requirements_confirmed, num_floors       │
  ▼                                                                  │
validate_node                                                        │
  │  Cross-checks requirements vs PlotInfo.                         │
  │  Nepal: checks road_width → required setback fits buildable zone│
  │  Multi-floor: checks FAR × plot area ≥ total room area program  │
  │  If impossible → shows error + asks to re-interview ────────────┘
  │  If feasible → proceed
  ▼
plan_node
  │  Retrieves rules from knowledge base (jurisdiction-aware).
  │  Calls LLM Design Advisor for qualitative strategy.
  │  Sets: retrieved_rules, design_strategy
  ▼
solve_node ─────────────────(UNSAT)──────────────► relax_node
  │  Runs OR-Tools CP-SAT solver — ALL FLOORS simultaneously.       │  Identifies lowest-priority
  │  Staircase continuity: stair position locked across floors.     │  soft constraint to relax.
  │  Sets: solver_status, floor_plans (one per floor, if SAT)       │  Re-solves.
  ◄────────────────────────────────────────────────────────────────-┘
  │(SAT)
  ▼
geometry_node
  │  Converts solver output to FloorPlan coordinates — ALL FLOORS.
  │  Builds wall segments, places doors and windows per floor.
  │  Validates staircase alignment between adjacent floors (≤ 0.5m delta).
  ▼
elevation_node                                     ← NEW
  │  Reads all FloorPlans + floor heights from requirements.
  │  Generates ElevationSet: front, rear, left, right elevations.
  │  Generates BuildingOutline3D for isometric view.
  │  Determines window/door positions on each facade from floor plans.
  │  Sets: elevation_set, elevation_complete
  ▼
approval_pause_node     ← interrupt_before: PAUSE #2
  │  Publishes design.approval_required event to Redis pub/sub.
  │  Browser receives via WebSocket → shows:
  │    - Floor plan (tabbed: Floor 1 / Floor 2 / ...)
  │    - Front elevation preview
  │    - 3D isometric outline
  │  Engineer can approve, request changes, or re-run from requirements.
  │  If feedback → back to plan_node with feedback as additional constraint.
  ▼ (approved)
draw_node
  │  Calls MCP tool server → ezdxf drawing for each floor plan.
  │  Draws: plot boundary, setbacks, rooms, walls, doors, windows, labels, title.
  │  Also draws: elevation DXF files (front/rear/left/right) + 3D outline DXF.
  ▼
verify_node
  │  Checks all hard rules against the actual FloorPlan (all floors).
  │  Checks spatial: dead ends, inaccessible rooms, staircase continuity.
  │  Nepal: seismic soft-storey check (ground floor not significantly weaker).
  │  Sets: verification_passed, verification_issues, verification_warnings
  │  If issues → revise_node (up to 3 times)
  ▼ (passed or max revisions reached)
save_output_node
  │  Uploads all DXF files to S3 (floor plans + elevations + 3D).
  │  Generates combined PDF set (all sheets at 1:100).
  │  Writes report.json with design rationale + compliance report.
  │  Updates DesignJobModel in PostgreSQL: status = completed.
  │  Publishes design.completed event via Redis → WebSocket.
  ▼
END
```

---

## Node Descriptions

### `load_project_node`
```
Input:  project_id, session_id (from CLI)
Output: project, plot_info, session_id

Actions:
- Load Project from SQLite via ProjectManager
- If plot_info is None → error: "Run 'civilengineer link-plot' first."
- If requirements already saved → ask engineer: "Use saved requirements or re-interview?"
- Initialize session in project.sessions
```

### `interview_node`
```
Input:  project, plot_info
Output: requirements, requirements_confirmed

Actions:
- Launch requirements_interview subgraph
- interrupt_before this node so engineer interacts with interview
- When interview subgraph completes → requirements set
- First interrupt: engineer sees summary and confirms
```

### `validate_node`
```
Input:  requirements, plot_info
Output: error (if infeasible) OR proceed signal

Checks:
- Total minimum area of all rooms > plot.area × FAR_limit → warn or block
- Number of floors × avg floor area < sum of minimum room areas → block
- If vastu_strict and plot orientation not compatible → warn
- If any constraint is literally impossible (0 sqft kitchen) → block
```

### `plan_node`
```
Input:  requirements, plot_info
Output: retrieved_rules, design_strategy

Actions:
1. Rule engine: load all applicable hard + soft rules for this room program
2. ChromaDB: retrieve top-k relevant rule snippets and design precedents
3. LLM: "Given these requirements, plot, and rules, provide a design strategy"
   Returns: DesignStrategy with soft_constraint_priority, layout_concept
```

### `solve_node`
```
Input:  requirements, plot_info, retrieved_rules, design_strategy, num_floors
Output: solver_status, floor_plans (one per floor, if SAT)

Actions:
1. Build CP-SAT model from requirements + rules (all floors in one model)
2. Add staircase continuity constraint:
   abs(stair_x[floor_i] - stair_x[floor_i+1]) ≤ 1   (in 50cm grid units)
   abs(stair_y[floor_i] - stair_y[floor_i+1]) ≤ 1
3. Apply soft constraint weights from design_strategy.soft_constraint_priority
4. Nepal: add soft-storey constraint (ground floor area ≥ 60% of upper floor area)
5. Run solver (timeout: 30 seconds × num_floors)
6. If SAT → extract room positions per floor → partial FloorPlans list
7. If UNSAT → solver_status = "unsat", increment solver_iterations
```

### `relax_node`
```
Input:  solver_status == "unsat", retrieved_rules, design_strategy, solver_iterations
Output: design_strategy (updated with one fewer soft constraint)

Actions:
- If solver_iterations >= 5 → error: DesignImpossibleError with explanation
- Ask LLM: "Which of these soft constraints should I relax first?"
  LLM picks the lowest-priority one from soft_constraint_priority
- Remove that rule from the objective
- Add to relaxed_constraints log
- Trigger re-run of solve_node
```

### `geometry_node`
```
Input:  floor_plans (partial, from solver, all floors)
Output: floor_plans (complete, with walls + doors + windows, all floors)
        building_design (container with all floors + BuildingOutline)

Actions:
1. For each floor:
   a. Convert solver grid positions to float meters
   b. Build WallSegments from room boundaries (dedup shared walls)
   c. Place doors on shared walls and exterior walls
   d. Place windows on exterior walls (ventilation-required rooms first)
   e. Final FloorPlan for this floor
2. Validate staircase alignment between adjacent floors
3. Build BuildingDesign from all FloorPlans + floor height schedule
```

### `elevation_node` *(new)*
```
Input:  building_design (all floors), requirements (floor heights, roof type)
Output: elevation_set (ElevationSet with front/rear/left/right + 3D)

Actions:
1. Extract exterior wall facade for each face (front, rear, left, right)
   using building_design.footprint + floor_plans door/window positions
2. For each face: build ElevationWall with WallOpenings (doors + windows per floor)
3. Determine roof type from requirements (default: terrace for Nepal)
4. Generate ElevationView for each face
5. Generate BuildingOutline3D: footprint extruded to total height + roof
6. Return ElevationSet — not yet drawn (draw_node handles DXF output)
```

### `human_review_node`
```
Input:  floor_plans, design_strategy
Output: human_feedback, approved (bool)

PAUSE POINT: interrupt_before
CLI shows:
  ─────────────────────────────────────────────────────────
  FLOOR PLAN LAYOUT READY FOR REVIEW
  Floor 1 of 1 | Total area: 2,280 sqft

  Rooms:
    Living Room      20.0ft × 15.0ft  = 300 sqft  [North face]
    Dining Room      14.0ft × 12.0ft  = 168 sqft
    Kitchen          12.0ft × 10.0ft  = 120 sqft  [East face, ext. wall]
    Master Bedroom   16.0ft × 14.0ft  = 224 sqft  [SW zone, att. bath]
    Bedroom 1        14.0ft × 12.0ft  = 168 sqft
    Bedroom 2        14.0ft × 11.0ft  = 154 sqft
    Bathroom (att.)   8.0ft × 6.0ft   =  48 sqft
    Bathroom          8.0ft × 6.0ft   =  48 sqft
    Staircase         8.0ft × 10.0ft  =  80 sqft
    Pooja Room        8.0ft × 8.0ft   =  64 sqft  [NE zone]

  Vastu: 7/8 rules satisfied. Kitchen not in SE (plot shape constraint).
  Constraint relaxed: vastu_kitchen_direction (not feasible on this plot)

  [Approve and draw] [Provide feedback] [Re-run with new requirements]
  ─────────────────────────────────────────────────────────

If engineer provides feedback → back to plan_node with feedback as additional_constraints
```

### `draw_node`
```
Input:  floor_plans (all), elevation_set, plot_info, requirements
Output: mcp_tool_log, drawing_complete

Actions (per floor plan DXF):
1. new_drawing() for each floor (floor_plan_F1.dxf, F2.dxf, ...)
2. setup_standard_layers()
3. Draw plot boundary, setback lines (Floor 1 only)
4. Draw room boundaries
5. Draw walls
6. Insert doors, windows, staircases
7. Add room labels + area annotations
8. Add dimensions
9. Add north arrow and title block

Actions (elevation DXFs — elevation_set):
10. new_drawing() for each face (elevation_front.dxf, etc.)
11. Draw wall outline with floor band lines
12. Draw window + door openings
13. Draw roof outline
14. Add height annotations
15. Add face label ("FRONT ELEVATION — NORTH")

Actions (3D outline DXF):
16. new_drawing() for building_3d.dxf
17. Extrude footprint to total building height (3D mesh)
18. Draw roof outline in 3D
19. Save as DXF R2018 with 3D entities
```

### `verify_node`
```
Input:  floor_plans, retrieved_rules, drawing_complete
Output: verification_passed, verification_issues, verification_warnings

Checks (code_compliance.py):
  - All hard rules from rule_engine still satisfied in final FloorPlan
  - No room area below NBC minimum

Checks (spatial_analyzer.py):
  - Every room is accessible (has at least one door to corridor or another room)
  - No dead-end corridors longer than 30 ft without a window
  - Staircase accessible from main circulation

Checks (structural_checker.py):
  - No room span exceeds 20 ft (max RCC slab span without beam)
  - If span > 15 ft → warning: "Consider intermediate beam"
```

### `revise_node`
```
Input:  verification_issues, floor_plans
Output: floor_plans (revised)

Actions:
- For each hard violation → targeted fix:
  "bedroom_02 area is 95 sqft (minimum 102)" → expand bedroom_02 by shrinking adjacent corridor
- Calls geometry_node logic for incremental adjustment
- Does NOT re-run the full solver (too slow) — applies geometry patches
- If fix creates new violations → mark as unresolvable, add to warnings
- Max 3 revision passes
```

### `save_output_node`
```
Actions:
1. Export DXF: ezdxf reads the saved .dwg and exports .dxf
2. Export PDF: AutoCAD plot API → .pdf
3. Write report.json:
   {
     "project_id": ..., "session_id": ...,
     "design_rationale": ...,
     "rooms": [...],
     "constraints_relaxed": [...],
     "verification_passed": ...,
     "issues": [...],
     "warnings": [...]
   }
4. Update ProjectSession in SQLite: status = "completed", output_files = [...]
5. Print final summary to CLI
```

---

## Interrupt Points

```python
graph = builder.compile(
    checkpointer=PostgresSaver.from_conn_string(DATABASE_URL),
    interrupt_before=["interview_node", "approval_pause_node"]
)
```

**interrupt_before interview_node:**
After loading the project, before the interview starts. Allows:
- Resuming with previously saved requirements (skip interview)
- Starting a fresh interview

**interrupt_before approval_pause_node:**
After floor plan + elevation views are computed, before drawing in ezdxf. Allows:
- Engineer to review all floors + front elevation + 3D outline in browser
- Request modifications without spending time on full DXF generation
- Approve and proceed to draw_node

---

## Session Resume

Because `PostgresSaver` checkpoints every node in the shared PostgreSQL database,
any Celery worker can resume any job — even after a crash or worker restart:

```bash
# Via API:
GET /api/v1/projects/{id}/designs/{session_id}/status
# → shows last completed node + current status

# Worker auto-resumes on restart using:
graph.invoke(None, config={"configurable": {"thread_id": session_id}})
# LangGraph reads the latest checkpoint and continues from where it left off
```

The graph resumes exactly where it was interrupted — even if the worker pod was
killed, restarted, or replaced by Kubernetes.
