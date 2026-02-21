# Reasoning Engine (Layer 2)

## Overview

The reasoning engine is the "brain" of the design pipeline. It takes
`DesignRequirements` + `PlotInfo` and produces a feasible room layout.

It has four components that work together:

```
Rule Engine          → Exact rule lookup (no LLM, zero hallucination risk)
Knowledge Retriever  → Semantic search for relevant context (ChromaDB)
LLM Design Advisor   → Qualitative reasoning ONLY (never numeric decisions)
OR-Tools CP-SAT      → Constraint satisfaction solver (produces room positions)
```

**Critical design principle:** The LLM never makes numeric decisions. It never says
"bedroom should be 110 sqft" or "setback should be 5 ft." Those numbers come from
the rule engine (compiled from NBC codes). The LLM's job is to say "given these
constraints, prioritize natural light in bedrooms over the southwest orientation
preference" — qualitative tradeoff reasoning.

---

## Component 1: Rule Engine (`rule_engine.py`)

### Purpose
Exact, deterministic lookup of architectural rules. Zero LLM involvement.

### How It Works

Rules are loaded at startup from `knowledge_base/structured/rules.json`
and compiled into `DesignRule` objects (via `knowledge/rule_compiler.py`).

```
At startup:
    rule_set = RuleCompiler.load("knowledge_base/structured/rules.json")
    hard_rules = rule_set.get_hard_rules()    # Must enforce in solver
    soft_rules = rule_set.get_soft_rules()    # Penalty objectives in solver

At design time, for each room type:
    applicable_rules = rule_set.get_rules_for_room(room_type)
    # Returns: min area, min dimension, ventilation req, vastu zone, etc.
```

### Example Rules (from rules.json)

```json
[
  {
    "rule_id": "NBC_3.2.1",
    "name": "Minimum bedroom area",
    "description": "Habitable rooms shall not be less than 9.5 square meters (102 sqft)",
    "source": "NBC India 2016, Part 4, Section 3.2.1",
    "category": "room_size",
    "severity": "hard",
    "rule_type": "min_area",
    "applies_to_room_types": ["bedroom", "master_bedroom"],
    "numeric_value": 102.0,
    "unit": "sqft"
  },
  {
    "rule_id": "NBC_3.2.2",
    "name": "Minimum kitchen area",
    "description": "Kitchen area shall not be less than 5 sqm (54 sqft)",
    "source": "NBC India 2016, Part 4, Section 3.2.2",
    "category": "room_size",
    "severity": "hard",
    "rule_type": "min_area",
    "applies_to_room_types": ["kitchen"],
    "numeric_value": 54.0,
    "unit": "sqft"
  },
  {
    "rule_id": "NBC_SEP_001",
    "name": "Toilet-kitchen separation",
    "description": "Toilet/WC shall not open directly into kitchen or dining room",
    "source": "NBC India 2016, Part 4, Section 3.5",
    "category": "separation",
    "severity": "hard",
    "rule_type": "must_separate",
    "applies_to_room_types": ["toilet", "bathroom"],
    "reference_room_types": ["kitchen", "dining_room"]
  },
  {
    "rule_id": "NBC_VENT_001",
    "name": "Kitchen ventilation",
    "description": "Kitchen must have at least one window opening to external air",
    "source": "NBC India 2016, Part 4, Section 3.7",
    "category": "ventilation",
    "severity": "hard",
    "rule_type": "ventilation_wall",
    "applies_to_room_types": ["kitchen"]
  },
  {
    "rule_id": "NBC_STAIR_001",
    "name": "Minimum staircase width",
    "description": "Minimum clear width of stairs in residential: 1.0m (3.28ft)",
    "source": "NBC India 2016, Part 4, Section 4.1",
    "category": "circulation",
    "severity": "hard",
    "rule_type": "min_dimension",
    "applies_to_room_types": ["staircase"],
    "numeric_value": 3.5,
    "unit": "ft"
  },
  {
    "rule_id": "VASTU_K_001",
    "name": "Kitchen Vastu zone",
    "description": "Kitchen preferred in southeast zone (Agni corner)",
    "source": "Vastu Shastra",
    "category": "vastu",
    "severity": "soft",
    "rule_type": "must_face_direction",
    "applies_to_room_types": ["kitchen"],
    "numeric_value": 135.0,
    "unit": "degrees"
  }
]
```

---

## Component 2: Knowledge Retriever (`knowledge_retriever.py`)

### Purpose
Semantic search over building code text, design guidelines, and examples.
Provides context for LLM qualitative reasoning.

### How It Works

```
At index time (civilengineer index):
    For each rule in rules.json:
        embed rule.embedding_text using all-MiniLM-L6-v2
        store in ChromaDB collection "building_rules"
    For each section in nbc_india_2016.pdf:
        extract text → chunk → embed → store in collection "nbc_text"
    For each entry in building_typologies.json:
        embed typology description → store in "typologies"

At retrieval time:
    query = f"{building_type} {rooms} {style} {facing} facing {constraints}"
    results = chroma.query(query_texts=[query], n_results=10)
    → returns: relevant rule snippets + design precedents
```

### Used By
The `plan_node` in the agent graph sends these snippets to the LLM along with
the `DesignRequirements`. The LLM uses them for context when formulating its
design strategy (qualitative).

---

## Component 3: LLM Design Advisor (`design_advisor.py`)

### Purpose
Generate a natural-language design strategy that guides the constraint solver's
soft constraint priorities.

### What It Does (and Does NOT Do)

**DOES:**
- "Given the north-facing plot and modern style, prioritize natural light in living room by placing it on the north face."
- "With vastu strict mode and only 2400 sqft, relax the pooja room vastu zone before relaxing bedroom orientation."
- "The irregular shape suggests placing the staircase in the southwest corner to use the awkward angle."

**DOES NOT:**
- Set any room areas (that's the rule engine)
- Set setback distances (that's NBC rules)
- Decide which hard rules to violate (hard rules are never relaxed)

### Output Format

```python
class DesignStrategy(BaseModel):
    """LLM output: qualitative design guidance for the solver."""
    primary_orientation_rooms: list[str]  # Which rooms to prioritize for natural light
    soft_constraint_priority: list[str]   # Soft rule IDs, in priority order (relax last = highest priority)
    layout_concept: str                   # One-paragraph design rationale
    special_considerations: list[str]     # Noted risks or tradeoffs
```

---

## Component 4: OR-Tools CP-SAT Constraint Solver (`constraint_solver.py`)

### Purpose
Produce a valid room layout (positions + dimensions) that satisfies all hard
constraints and optimizes soft constraints.

### Why CP-SAT

Room layout is a **constraint satisfaction + optimization problem**:
- Variables: room positions (x, y) and dimensions (width, height)
- Hard constraints: NBC rules (must be satisfied)
- Soft constraints (objectives): Vastu, adjacency preferences, light optimization

CP-SAT handles integer/combinatorial variables, rectangle non-overlap, and
weighted objective functions. Z3 (SMT) times out on geometric packing.

### Coordinate System

All variables are in **half-foot units** (2 units = 1 foot). This keeps everything
as integers (CP-SAT works with integers only) while giving 6-inch precision.

Example: a 10ft × 12ft bedroom = variables constrained to 20 × 24 units.

### Decision Variables

For each room `i`:
```
x[i]: int  — left edge of room (in half-feet from plot origin)
y[i]: int  — bottom edge
w[i]: int  — width (in half-feet)
h[i]: int  — height
```

### Hard Constraints (from HARD DesignRules)

```
1. Bounds: all rooms within buildable zone
   x[i] >= bz.x, x[i] + w[i] <= bz.x + bz.width
   y[i] >= bz.y, y[i] + h[i] <= bz.y + bz.height

2. No overlap: for every pair (i, j)
   x[i]+w[i] <= x[j]  OR
   x[j]+w[j] <= x[i]  OR
   y[i]+h[i] <= y[j]  OR
   y[j]+h[j] <= y[i]
   (Encoded as: at least one of these must be true)

3. Minimum area: w[i] * h[i] >= min_area_units
   (Linearized via McCormick envelope for product constraint)

4. Minimum dimension: w[i] >= min_w AND h[i] >= min_h

5. Kitchen touches external wall:
   x[kitchen] == bz.x OR x[kitchen]+w[kitchen] == bz.x+bz.width
   OR y[kitchen] == bz.y OR y[kitchen]+h[kitchen] == bz.y+bz.height

6. Toilet not adjacent to kitchen:
   If toilet shares wall with kitchen → infeasible flag
   (Encoded as minimum gap constraint)

7. Staircase min width: w[stair] >= 7 (3.5 ft × 2)
```

### Soft Constraints (Objectives)

```
Maximize:
  + adjacency_score: sum of (1 if adjacent_rooms[i][j] else 0) weighted by preference
  + natural_light: bedrooms on north/east face (for north-facing plot)
  + vastu_compliance: sum of rooms in preferred vastu zones
  - corridor_waste: total unused area that becomes passage

These are combined into a single weighted objective:
  maximize: w1 * adjacency + w2 * light + w3 * vastu - w4 * waste

Weights come from design_strategy.soft_constraint_priority from the LLM advisor.
```

### UNSAT Handling (Constraint Relaxation Loop)

```
Round 1: solve with all constraints
  → SAT: proceed to geometry engine
  → UNSAT: continue

Round 2: ask LLM "which soft constraint to relax first?"
  LLM returns the lowest-priority soft constraint ID
  Remove it from the objective / relax its weight to 0
  Re-solve. Log: relaxed_constraints.append(rule_id)

Repeat up to 5 rounds.

If UNSAT after 5 rounds:
  Check if hard constraints themselves are infeasible
  Generate human-readable explanation:
    "Your plot (2400 sqft) cannot fit a 3BHK under NBC 2016 minimum room areas.
     The minimum required built-up area is 2,650 sqft. Options:
     1. Reduce to 2BHK
     2. Increase to 2 floors
     3. Reduce individual room areas (requires variance approval)"
  Raise DesignImpossibleError → agent ends with this message
```

---

## Solver Output Format

The solver returns room assignments (not Pydantic yet — raw data):

```python
{
  "bedroom_01": {"x": 10, "y": 20, "w": 24, "h": 28},   # half-feet
  "kitchen_01": {"x": 0,  "y": 0,  "w": 20, "h": 18},
  ...
}
```

The geometry engine converts this to `RoomLayout` objects with real-foot `Rect2D`.

---

## Summary: Which Component Decides What

| Decision | Component | Why |
|----------|-----------|-----|
| Minimum bedroom area (102 sqft) | Rule Engine | Hard fact from NBC — zero ambiguity |
| Kitchen must touch external wall | Rule Engine | Hard fact from NBC |
| Which room gets north light | LLM Advisor | Qualitative tradeoff |
| Which vastu rule to relax first | LLM Advisor | Priority judgment |
| Exact room coordinates | OR-Tools CP-SAT | Combinatorial optimization |
| Staircase width (3.5 ft) | Rule Engine | Hard fact from NBC |
| Bedroom preferred in SW (vastu) | Rule Engine (soft) + LLM priority | Rule is soft; priority is LLM |
