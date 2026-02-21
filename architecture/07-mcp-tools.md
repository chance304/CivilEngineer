# MCP Tool Reference (Layer 4)

## Overview

The MCP server is the bridge between the LangGraph agent and AutoCAD. It exposes
AutoCAD drawing operations as AI-callable tools using the FastMCP framework.

**Transport:** stdio (not HTTP). This is a local workstation tool.
**Entry point:** `src/civilengineer/mcp_server/server.py`

---

## Tool Categories

### Session Tools (connect + file management)

```
connect_autocad()
    Connect to the running AutoCAD instance via COM automation.
    Must be called before any drawing tools.
    Returns: {session_id, dwg_path, autocad_version}

new_drawing(template: str = "Architectural")
    Open a new AutoCAD drawing from a template.
    template: "Architectural" | "Civil" | "Metric"
    Returns: {dwg_path}

save_drawing(dwg_path: str, export_pdf: bool = False)
    Save the current drawing to disk.
    Returns: {saved_path, pdf_path}

set_drawing_units(unit: str, scale: float)
    Configure drawing units and scale.
    unit: "feet" | "mm" | "meters"
    scale: model space units per real-world unit (typically 1.0)
    Returns: {confirmed_unit, confirmed_scale}
```

---

### Layer Management

```
create_layer(
    name: str,
    color_index: int,
    linetype: str = "Continuous",
    lineweight: float = 0.25
)
    Create an AutoCAD layer.
    color_index: AutoCAD ACI color (1=red, 2=yellow, 3=green, etc.)
    Returns: {layer_name}

set_active_layer(layer_name: str)
    Set the current active layer for subsequent operations.
    Returns: {confirmed_layer}

setup_standard_layers()
    Create all standard AIA layers for this project in one call.
    Called once at the start of a drawing session.
    Returns: {layers_created: list[str]}
```

---

### Drawing Primitives

```
draw_wall(
    x1: float, y1: float,
    x2: float, y2: float,
    thickness_ft: float = 0.75,
    wall_type: str = "external",
    layer: str = "A-WALL-EXTR"
)
    Draw a wall segment as a thick polyline.
    Coordinates in feet in model space (1 unit = 1 foot).
    wall_type: "external" | "internal_load" | "internal_partition"
    Returns: {object_handle, wall_length_ft}

draw_room_boundary(
    x: float, y: float,
    width_ft: float, height_ft: float,
    room_name: str,
    room_type: str,
    layer: str = "A-ROOM-OTLN"
)
    Draw a closed rectangular room boundary.
    x, y: bottom-left corner in feet.
    Returns: {object_handles: list[str], room_area_sqft}

draw_polyline(
    points: list[tuple[float, float]],
    closed: bool = False,
    layer: str = "0"
)
    Draw an open or closed polyline through (x, y) points.
    Used for irregular walls, plot boundary, setback lines.
    Returns: {object_handle}

draw_plot_boundary(polygon: list[tuple[float, float]])
    Draw the plot boundary (copied from PlotInfo.polygon).
    Uses layer C-PLOT.
    Returns: {object_handle}

draw_setback_lines(
    buildable_zone_x: float, buildable_zone_y: float,
    buildable_zone_width: float, buildable_zone_height: float
)
    Draw the buildable zone as dashed reference lines.
    Uses layer C-SETB.
    Returns: {object_handles: list[str]}
```

---

### Architectural Elements

```
insert_door(
    x: float, y: float,
    width_ft: float = 3.0,
    swing_angle_deg: float = 90.0,
    door_type: str = "swing_single",
    layer: str = "A-DOOR"
)
    Insert a door symbol at position (x, y).
    door_type: "swing_single" | "swing_double" | "sliding" | "pocket"
    Returns: {object_handle}

insert_window(
    x: float, y: float,
    width_ft: float = 4.0,
    height_ft: float = 4.0,
    sill_height_ft: float = 3.0,
    layer: str = "A-WIND"
)
    Insert a window symbol on a wall.
    Returns: {object_handle}

insert_staircase(
    x: float, y: float,
    width_ft: float = 4.0,
    run_ft: float = 10.0,
    num_risers: int = 13,
    direction: str = "up",
    layer: str = "A-STAIR"
)
    Insert a staircase symbol.
    direction: "up" | "down" | "both"
    Returns: {object_handle}

insert_column(
    x: float, y: float,
    size_ft: float = 1.0,
    shape: str = "square",
    layer: str = "S-COLS"
)
    Insert a structural column symbol.
    shape: "square" | "circular"
    Returns: {object_handle}
```

---

### Annotation Tools

```
add_room_label(
    room_name: str,
    area_sqft: float,
    x: float, y: float,
    text_height_ft: float = 1.0,
    layer: str = "A-ROOM-LABL"
)
    Add room name + area text at position (x, y).
    Returns: {object_handles: list[str]}

add_dimension(
    x1: float, y1: float,
    x2: float, y2: float,
    offset_ft: float = 2.0,
    layer: str = "A-ANNO-DIMS"
)
    Add a linear dimension between two points.
    offset_ft: distance the dimension line is from the measured line.
    Returns: {object_handle}

add_north_arrow(
    x: float, y: float,
    facing_direction: str = "north",
    layer: str = "A-ANNO-SYMB"
)
    Insert a north arrow symbol indicating which direction is north.
    Returns: {object_handle}

add_title_block(
    project_name: str,
    client_name: str,
    drawn_by: str = "AI Architectural Copilot",
    date: str = "",
    scale: str = "1:100",
    layer: str = "A-ANNO-TITL"
)
    Insert a title block in paper space.
    Returns: {object_handle}
```

---

### Query Tools (Read-Only, Used by Verification)

```
get_drawing_extents()
    Return the bounding box of all entities in model space.
    Returns: {min_x, min_y, max_x, max_y, width_ft, height_ft}

get_layer_list()
    Return all layers in the current drawing.
    Returns: {layers: list[{name, color, is_on, is_frozen}]}

measure_distance(x1: float, y1: float, x2: float, y2: float)
    Measure distance between two points.
    Returns: {distance_ft}

get_entities_on_layer(layer_name: str)
    Return all entity handles on a layer.
    Used by verification to check what was actually drawn.
    Returns: {handles: list[str], count: int}
```

---

## Layer Name Reference

| Layer | Color | Purpose |
|-------|-------|---------|
| `A-WALL-EXTR` | 1 (Red) | External load-bearing walls |
| `A-WALL-INT-LOAD` | 2 (Yellow) | Internal load-bearing walls |
| `A-WALL-PART` | 3 (Green) | Internal partition walls |
| `A-DOOR` | 4 (Cyan) | Doors and swings |
| `A-WIND` | 5 (Blue) | Windows |
| `A-ROOM-OTLN` | 6 (Magenta) | Room boundary outlines (reference) |
| `A-ROOM-LABL` | 7 (White) | Room name and area text |
| `A-STAIR` | 8 (Dark grey) | Staircase symbols |
| `S-COLS` | 11 (Red variant) | Structural columns |
| `C-PLOT` | 41 (Yellow variant) | Plot boundary |
| `C-SETB` | 42 (Cyan variant) | Setback reference lines (dashed) |
| `A-ANNO-DIMS` | 2 (Yellow) | Dimensions |
| `A-ANNO-TEXT` | 7 (White) | General annotation text |
| `A-ANNO-SYMB` | 7 (White) | North arrow, scale bar |
| `A-ANNO-TITL` | 7 (White) | Title block |

---

## Error Handling

All tool calls return a `MCPToolResult`. On failure:

```json
{
  "status": "failure",
  "error_message": "AutoCAD COM error: CALL_REJECTED. AutoCAD may be busy.",
  "autocad_object_handles": []
}
```

The `connection_guard.py` handles:
- `CLASS_NOT_REGISTERED` → AutoCAD not running → clear user message
- `CALL_REJECTED` → AutoCAD busy (dialog open) → retry once after 2s
- `ACCESS_DENIED` → COM automation disabled in AutoCAD settings → user instruction to enable it

---

## Calling Sequence for a Full Floor Plan

The `draw_node` calls tools in this order:

```
1. connect_autocad()
2. new_drawing("Architectural")
3. set_drawing_units("feet", 1.0)
4. setup_standard_layers()
5. draw_plot_boundary(plot_info.polygon)
6. draw_setback_lines(buildable_zone)
7. For each room in floor_plan.rooms:
     draw_room_boundary(room.bounds.x, room.bounds.y, ...)
8. For each wall in floor_plan.walls:
     draw_wall(wall.start.x, wall.start.y, ...)
9. For each room:
     For each door: insert_door(...)
     For each window: insert_window(...)
     add_room_label(room.room_type, room.actual_area_sqft, room.bounds.center)
10. For each room pair: add_dimension(...)
11. add_north_arrow(x, y, plot_info.facing)
12. add_title_block(project_name, client_name, ...)
13. save_drawing(output_path, export_pdf=True)
```
