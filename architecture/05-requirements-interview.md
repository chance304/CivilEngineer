# Requirements Interview (Layer 0.75)

## Purpose

Replace the simple "parse a single text prompt" approach with a structured, adaptive
multi-turn conversation. The interview ensures the system understands the engineer's
intent before wasting computation on the wrong design. The output is a confirmed
`DesignRequirements` object saved to the project.

---

## Design Principles

1. **The system asks, not the user.** The engineer doesn't need to know what data
   the solver needs. The interview collects it through natural conversation.

2. **Adaptive.** Questions change based on previous answers. A 1-floor commercial
   project gets different questions than a 3-floor vastu-compliant residence.

3. **Plot-aware.** The interview starts with the PlotInfo already loaded. It uses
   the plot area and facing to contextualize questions (e.g., warn if 3BHK is
   too large for the plot).

4. **Confirmable.** Before saving, the system summarizes everything it understood.
   The engineer can edit any field before confirming.

5. **Re-runnable.** The engineer can re-run the interview at any time to update
   requirements. Each confirmed run creates a new requirements snapshot.

---

## Interview Flow

```
ENTRY: plot_info is loaded; project is active

PHASE 1 — Context Introduction
  System: "We're designing for the {client_name} project at {location}.
           Your plot is {area} sqft ({width}ft × {depth}ft), {facing} facing.
           Let's define the building requirements."

PHASE 2 — Building Type
  Q: "What type of building is this?"
  Options: Residential / Commercial / Mixed-use / Industrial
  → Sets: building_type

PHASE 3 — Scale
  Q: "How many floors?"
  Input: integer (1–5)
  → Sets: total_floors

  Q: "Do you have a target built-up area?"
  Options: Yes (specify sqft) / No (let the system optimize)
  → Sets: target_built_up_area_sqft

  [ADAPTIVE CHECK — warn if infeasible]
  If requested area > plot.area * 2.5 (typical FAR limit):
    "Note: {area} sqft on a {plot.area} sqft plot may exceed FAR limits for {city}.
     The system will alert you if constraints make this impossible."

PHASE 4 — Room Program
  Q: "How many bedrooms?"
  → count for RoomType.BEDROOM

  If bedrooms ≥ 1:
    Q: "Is one of them a master bedroom with an attached bathroom?"
    → RoomRequirement(room_type=MASTER_BEDROOM, attached_bathroom=True)

  Q: "How many bathrooms? (separate from attached ones)"
  → count for RoomType.BATHROOM

  Q: "Do you need a separate dining room, or combined living-dining?"
  → separate DINING_ROOM entry or note in living room

  Q: "Kitchen type: open (part of living), semi-open, or closed?"
  → sets kitchen notes / placement constraints

  [ADAPTIVE — multi-floor]
  If total_floors > 1:
    Q: "Repeat the program for each floor, or same on all floors?"

PHASE 5 — Special Rooms
  Q: "Do you need any of these?"
  [multi-select]
    □ Pooja room
    □ Study / home office
    □ Servant quarters
    □ Garage / parking
    □ Storeroom
    □ Lift / elevator shaft
    □ Terrace access
  → Sets has_* flags and adds RoomRequirement entries

PHASE 6 — Style
  Q: "Architectural style preference?"
  Options: Modern / Traditional / Classical / Minimal / Vernacular
  → Sets: style

PHASE 7 — Vastu
  Q: "Should the design be Vastu compliant?"
  Options: Yes — strict / Yes — flexible / No
  → Sets: vastu_compliant, vastu_priority

  If vastu = yes:
    Q: "Any specific Vastu preferences?"
    Examples: "Master bedroom in southwest", "Kitchen in southeast", "Pooja room northeast"
    → Sets: vastu_zone on relevant RoomRequirements

PHASE 8 — Constraints + Special Notes
  Q: "Any hard constraints or specific requirements?"
  Freeform text. Examples:
    "Main entrance must face north"
    "Master bedroom on ground floor for elderly parent"
    "No windows on south wall"
  → Appended to: additional_constraints list

PHASE 9 — Summary + Confirmation
  System shows:
  ─────────────────────────────────────────────────────
  DESIGN BRIEF SUMMARY
  Project: {name} | Client: {client_name}
  Plot: {area} sqft | Facing: {facing}

  Building: Residential, {floors} floor(s)
  Built-up area target: {area or "auto"} sqft
  Style: {style}
  Vastu: {yes/no + priority}

  Rooms:
    • 1× Master Bedroom (attached bathroom)  [SW preferred]
    • 2× Bedroom
    • 2× Bathroom
    • 1× Living Room + Dining (combined)
    • 1× Kitchen (closed)
    • 1× Pooja Room                           [NE preferred]
    • 1× Garage

  Constraints:
    • Apply NBC India 2016
    • Vastu: strict compliance
    • Main entrance faces north

  ─────────────────────────────────────────────────────
  Does this look correct?
  [Confirm] [Edit specific field] [Start over]

PHASE 10 — Save
  If confirmed → save to projects/{id}/requirements.json
  System: "Requirements saved. Run 'civilengineer design' to start."
```

---

## Adaptive Logic Rules

| Condition | Adaptation |
|-----------|------------|
| `plot.area < 800 sqft` | Warn before asking room count: "Small plot. 2BHK is typically max for this area." |
| `plot.is_rectangular == false` | Ask: "Irregular plot detected. Prioritize rectangular rooms or follow plot boundary?" |
| `building_type == "commercial"` | Skip vastu, bedroom, pooja questions. Add: parking, reception, office layout questions. |
| `vastu_compliant == true` | Add vastu zone questions for each room type. |
| `total_floors > 1` | Ask about staircase position preference and terrace/terrace-garden access. |
| `attached_bathroom == true` | Automatically add toilet/bathroom requirement with adjacency constraint. |
| `has_garage == true` | Ask: "Attached garage (part of built-up) or separate structure?" |
| `has_lift == true` | Ask: "Lift shaft only, or machine room above?" Add to staircase area. |

---

## Implementation: LangGraph Subgraph

The interview is a self-contained LangGraph subgraph. It is called from `interview_node`
in the main agent graph.

### Interview State

```python
class InterviewState(TypedDict):
    project_id: str
    plot_info: PlotInfo                 # Read-only context
    phase: str                          # Current interview phase name
    answers: dict[str, Any]             # Accumulated answers, keyed by question_id
    conversation: Annotated[list, add_messages]  # Full message history
    is_complete: bool
    confirmed_requirements: Optional[DesignRequirements]
    edit_requested: Optional[str]       # Which field engineer wants to edit
```

### Subgraph Nodes

```
greet_node → building_type_node → scale_node → room_program_node
    → special_rooms_node → style_node → vastu_node → constraints_node
    → summary_node ─(confirmed)→ save_node → END
                   ─(edit)─────→ edit_node → back to relevant phase
                   ─(restart)──→ greet_node
```

### Human Input Mechanism

The interview subgraph uses `interrupt_after` on each question node. The CLI's
`design_commands.py` loops:
```python
while not interview_complete:
    user_input = input("> ")
    state = graph.invoke({"human_input": user_input}, config=checkpoint)
    print(state["last_question"])
```

---

## Files

| File | Responsibility |
|------|----------------|
| `requirements_interview/interviewer.py` | LangGraph subgraph definition. Phase routing. |
| `requirements_interview/questions.py` | Question bank. Adaptive logic rules. Summary renderer. |
| `requirements_interview/interview_state.py` | `InterviewState` TypedDict. |
| `requirements_interview/prompts/interview_system.md` | LLM system prompt for natural conversation. |

---

## Interview System Prompt (Excerpt)

```
You are a professional architectural design assistant conducting a requirements
interview for a civil engineer. Your job is to gather all information needed to
design a building.

Context:
  Plot: {plot.area_sqft} sqft, {plot.width_ft}ft × {plot.depth_ft}ft, {plot.facing} facing
  Confidence in plot data: {plot.extraction_confidence}%

Rules for the interview:
1. Ask one question at a time. Wait for the answer.
2. Ask follow-up questions when answers are ambiguous.
3. If the engineer's request seems infeasible given the plot size, warn them but
   still record their preference.
4. Stick to the question sequence. Do not jump ahead.
5. When summarizing, be precise — repeat back exact numbers and preferences.
6. Never make up defaults silently. If the engineer hasn't specified something,
   ask before assuming.

Current phase: {phase}
Questions remaining: {remaining_phases}
```
