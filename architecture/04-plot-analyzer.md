# Plot Analyzer (Layer 0.5)

## Purpose

The plot DWG file is the ground truth for the project. The Plot Analyzer reads it
once when the engineer links it to the project and produces a `PlotInfo` object.
No downstream system makes assumptions about the plot — they all consume `PlotInfo`.

---

## Why ezdxf (Not AutoCAD COM)

The plot analyzer runs at project setup time — AutoCAD may not be open. The engineer
might be setting up the project on a laptop without AutoCAD. `ezdxf` reads DXF and
DWG files as a pure Python library with no dependencies on installed software.

Note: ezdxf natively reads DXF files. For DWG, it integrates with the free ODA File
Converter if installed, or the engineer can export to DXF from AutoCAD first. Both
workflows are supported.

---

## Extraction Strategy

### 1. Plot Boundary (`boundary_extractor.py`)

Tries to find the plot boundary polygon in this order:

```
Priority 1 — Named layer lookup
    Search for a closed LWPOLYLINE or POLYLINE on layers:
    "PLOT", "BOUNDARY", "SITE", "C-PLOT", "PLOT-BOUNDARY"
    If found → use as plot boundary

Priority 2 — Largest closed polygon heuristic
    Find all closed LWPOLYLINEs in the drawing
    If only one large polygon exists → likely the plot boundary
    Threshold: polygon area > 50% of drawing extent area

Priority 3 — Hatch entity
    Look for a HATCH entity covering a large area
    Extract its boundary path as the plot polygon

Priority 4 — LLM disambiguation (fallback)
    Render all closed polylines as text descriptions
    Ask LLM: "Which of these polygons is the plot boundary?"
    Use LLM's selection

    If LLM uncertain → extraction_confidence < 0.5
    CLI shows warning, asks engineer to confirm
```

### 2. Scale / Units (`dwg_reader.py`)

```
Read DXF header: $INSUNITS variable
    0 = unitless (ask engineer)
    1 = inches
    2 = feet
    4 = mm
    5 = cm
    6 = meters

Compute scale_factor = conversion to feet
    If feet: 1.0
    If mm: 1 / 304.8
    If meters: 3.28084
    If inches: 1 / 12
    If unitless: attempt to infer from polygon dimensions
        (a residential plot is typically 30–200 ft wide)
```

### 3. Orientation / North Direction (`orientation_detector.py`)

```
Priority 1 — NORTH_ARROW block
    Search block table for: "NORTH", "NORTH_ARROW", "COMPASS",
    "ARROW_N", "NORTHARROW" (case-insensitive)
    If found → read block insertion rotation angle → north_direction_deg

Priority 2 — Text entity
    Search for TEXT/MTEXT containing "N" or "NORTH"
    that is positioned near an arrow/line entity
    Compute direction from text position to arrow tip

Priority 3 — Block attribute
    Search for INSERT entities with attribute "FACING" or "ORIENTATION"

Priority 4 — Assume north = up (0 degrees)
    Log: extraction_notes.append("North direction assumed (up). Verify with engineer.")
    extraction_confidence -= 0.2
```

### 4. Site Features (`site_feature_extractor.py`)

```
Look for:
    BLOCK entities with names containing: "TREE", "PLANT", "WELL", "BORE"
    TEXT entities: "TREE", "NALA", "ROAD", "DRAIN", existing structure labels
    HATCH entities away from main plot boundary (existing structures)

Return list of strings: ["tree_northwest", "well_center", "road_north"]
These are informational — displayed to engineer, used in interview context
```

---

## Output: PlotInfo

After extraction:

```json
{
  "dwg_source_path": "C:/Projects/Site/plot.dwg",
  "polygon": [
    {"x": 0.0, "y": 0.0},
    {"x": 40.0, "y": 0.0},
    {"x": 40.0, "y": 60.0},
    {"x": 0.0, "y": 60.0}
  ],
  "area_sqft": 2400.0,
  "width_ft": 40.0,
  "depth_ft": 60.0,
  "is_rectangular": true,
  "north_direction_deg": 0.0,
  "facing": "north",
  "existing_features": ["road_north"],
  "scale_factor": 1.0,
  "extraction_confidence": 0.95,
  "extraction_notes": []
}
```

---

## Handling Irregular Plots

If `is_rectangular = false`:

1. The `polygon` field contains the actual vertices (not just a bounding box).
2. The `Rect2D buildable_zone` in `FloorPlan` is computed as:
   - Shapely: `polygon.buffer(-setback_ft)` = inset polygon by setback distance
3. The constraint solver uses the inset polygon as the feasible region for room placement.
4. Rooms are still rectangular (Phase 1-5 assumption).
5. Phase 6+ can add angled rooms that follow the plot boundary.

---

## CLI Output

```
$ civilengineer link-plot site.dwg

Analyzing plot DWG...
  DXF version: R2018
  Units: feet (scale: 1.0)

Plot boundary found (confidence: 95%)
  Layer: C-PLOT
  Shape: Rectangular
  Area: 2,400 sqft (40ft × 60ft)
  Facing: North (north arrow block detected)

Site features detected:
  - Road on north side

Plot analysis saved to: projects/PRJ-001/plot_info.json

Ready to run: civilengineer interview
```

If confidence is low:

```
WARNING: Plot boundary detection is uncertain (confidence: 45%)
  Found 3 large closed polylines. Could not determine which is the plot boundary.

  Please confirm: run AutoCAD and ensure the plot boundary is on layer "C-PLOT"
  Then re-run: civilengineer link-plot site.dwg

  Or proceed anyway: civilengineer link-plot site.dwg --accept-uncertain
```

---

## Files

| File | Responsibility |
|------|----------------|
| `plot_analyzer/dwg_reader.py` | Entry point. Opens DXF with ezdxf. Calls other modules. |
| `plot_analyzer/boundary_extractor.py` | Finds plot boundary polygon. Returns `list[Point2D]`. |
| `plot_analyzer/orientation_detector.py` | Finds north direction. Returns `float` (degrees). |
| `plot_analyzer/site_feature_extractor.py` | Finds trees, roads, existing structures. |

---

## Error Handling

| Error | Response |
|-------|----------|
| File not found | Clear message: "File not found: {path}. Check the path and try again." |
| File is DWG, no ODA converter | "File is a .dwg binary. Export to .dxf from AutoCAD, or install ODA File Converter." |
| No closed polygons found | "No plot boundary found. Ensure plot outline is a closed polyline in the DWG." |
| Scale factor unresolvable | "Cannot determine drawing units. Use --scale {feet_per_unit} to specify." |
| Extraction confidence < 0.5 | Warning shown, engineer must confirm or re-run with --accept-uncertain |
