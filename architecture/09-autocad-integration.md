# AutoCAD Integration (Layer 5)

## Overview

The AutoCAD layer provides direct COM automation access to AutoCAD. All MCP tool
calls route through this layer. The design principle is: **MCP tools are thin wrappers;
all AutoCAD knowledge lives here.**

---

## COM Automation Architecture

```
MCP Tool (e.g., draw_wall)
    │
    ▼
AutoCADClient.draw_wall(x1, y1, x2, y2, ...)
    │
    ▼
ConnectionGuard.execute_with_guard(driver, command_fn, ...)
    │  ├── Checks connection alive
    │  ├── Handles COM errors (retry once, then raise typed exception)
    │  └── Logs call + result via structlog
    ▼
AutoCADCOMDriver.draw_wall_polyline(...)
    │
    ▼
win32com.client → AutoCAD.Application.ActiveDocument.ModelSpace
    → .AddLWPolyline(pts)  /  .AddLine(pt1, pt2)  /  etc.
```

---

## COM Driver Design (`com_driver.py`)

### Connection

```python
acad = win32com.client.GetActiveObject("AutoCAD.Application")
doc  = acad.ActiveDocument
model_space = doc.ModelSpace
```

- `GetActiveObject` requires AutoCAD to be running.
- If AutoCAD is not running → `pythoncom.com_error` with `CLASS_NOT_REGISTERED` code.
- The `ConnectionGuard` translates this to `AutoCADNotRunningError` with a helpful message.

### Coordinate Handling

AutoCAD COM requires coordinates as win32com VARIANT arrays:

```python
import win32com.client as wc
import pythoncom

def make_point(x: float, y: float, z: float = 0.0):
    return wc.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        [x, y, z]
    )

def make_point_list(*points: tuple[float, float]):
    flat = []
    for x, y in points:
        flat.extend([x, y, 0.0])
    return wc.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)
```

All coordinates use: **1 model space unit = 1 foot**. This is configured via
`set_drawing_units("feet", 1.0)` at the start of each session.

### Drawing a Wall

```python
def draw_wall_polyline(
    self,
    x1: float, y1: float,
    x2: float, y2: float,
    thickness_ft: float,
    layer: str
) -> str:
    pts = make_point_list((x1, y1), (x2, y2))
    pline = self.model_space.AddLWPolyline(pts)
    pline.ConstantWidth = thickness_ft
    pline.Layer = layer
    self.doc.SendCommand("REGEN\n")  # Force display refresh
    return pline.Handle  # AutoCAD entity handle (hex string)
```

### Drawing a Room Boundary

```python
def draw_room_boundary(self, x, y, width, height, layer) -> list[str]:
    handles = []
    walls = [
        ((x, y),         (x+width, y)),        # Bottom
        ((x+width, y),   (x+width, y+height)), # Right
        ((x+width, y+h), (x, y+height)),        # Top
        ((x, y+height),  (x, y)),               # Left
    ]
    for (x1, y1), (x2, y2) in walls:
        line = self.model_space.AddLine(
            make_point(x1, y1),
            make_point(x2, y2)
        )
        line.Layer = layer
        handles.append(line.Handle)
    return handles
```

---

## Layer Manager (`layer_manager.py`)

Creates all standard AIA layers once at the start of a session:

```python
STANDARD_LAYERS = [
    {"name": "A-WALL-EXTR",     "color": 1,  "linetype": "Continuous", "lw": 0.50},
    {"name": "A-WALL-INT-LOAD", "color": 2,  "linetype": "Continuous", "lw": 0.35},
    {"name": "A-WALL-PART",     "color": 3,  "linetype": "Continuous", "lw": 0.25},
    {"name": "A-DOOR",          "color": 4,  "linetype": "Continuous", "lw": 0.25},
    {"name": "A-WIND",          "color": 5,  "linetype": "Continuous", "lw": 0.25},
    {"name": "A-ROOM-OTLN",     "color": 6,  "linetype": "Continuous", "lw": 0.18},
    {"name": "A-ROOM-LABL",     "color": 7,  "linetype": "Continuous", "lw": 0.18},
    {"name": "A-STAIR",         "color": 8,  "linetype": "Continuous", "lw": 0.25},
    {"name": "S-COLS",          "color": 11, "linetype": "Continuous", "lw": 0.50},
    {"name": "C-PLOT",          "color": 41, "linetype": "Continuous", "lw": 0.70},
    {"name": "C-SETB",          "color": 42, "linetype": "DASHED",     "lw": 0.18},
    {"name": "A-ANNO-DIMS",     "color": 2,  "linetype": "Continuous", "lw": 0.18},
    {"name": "A-ANNO-TEXT",     "color": 7,  "linetype": "Continuous", "lw": 0.18},
    {"name": "A-ANNO-SYMB",     "color": 7,  "linetype": "Continuous", "lw": 0.18},
    {"name": "A-ANNO-TITL",     "color": 7,  "linetype": "Continuous", "lw": 0.18},
]
```

---

## Transaction Manager (`transaction_manager.py`)

For performance, batches multiple drawing commands before triggering a REGEN:

```python
class DrawingTransaction:
    """Context manager that batches AutoCAD commands."""

    def __enter__(self):
        self.doc.SendCommand("UNDO MARK\n")  # Create undo checkpoint
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.doc.SendCommand("UNDO BACK\n")  # Roll back on error
            return False
        self.doc.SendCommand("REGEN\n")
        self.doc.SendCommand("ZOOM EXTENTS\n")
        return False
```

Usage in draw_node:
```python
with DrawingTransaction(driver):
    for room in floor_plan.rooms:
        driver.draw_room_boundary(...)
    for wall in floor_plan.walls:
        driver.draw_wall_polyline(...)
```

If drawing fails mid-way, the UNDO BACK command reverts AutoCAD to the clean state.

---

## Error Handler (`error_handler.py`)

### COM Error Codes

| Code | Meaning | Response |
|------|---------|----------|
| `-2147221005` | CLASS_NOT_REGISTERED | AutoCAD not running. Start AutoCAD and try again. |
| `-2147220994` | CALL_REJECTED | AutoCAD busy. Retry once after 2 seconds. |
| `-2147467259` | E_FAIL | Command failed. Log details, raise AutoCADCommandError. |
| `-2147220895` | INVALID_INDEX | Layer/object not found. Check layer names. |

### Typed Exceptions

```python
class AutoCADNotRunningError(Exception):
    """AutoCAD is not running or not accessible via COM."""

class AutoCADBusyError(Exception):
    """AutoCAD is busy (a dialog may be open)."""

class AutoCADCommandError(Exception):
    """A specific AutoCAD command failed."""

class AutoCADLayerError(AutoCADCommandError):
    """A layer operation failed (layer not found, etc.)."""
```

---

## DXF Fallback (When AutoCAD Not Running)

The `ezdxf` library can produce DXF files without AutoCAD. Used as fallback in:
- Testing environments (no AutoCAD installed)
- `civilengineer design --no-autocad` flag (Phase 7+)

```python
class EzdxfDriver:
    """
    DXF file generator using ezdxf.
    Produces geometrically identical output to COM driver.
    Does not produce .dwg (only .dxf).
    """
    def __init__(self, output_path: str):
        self.doc = ezdxf.new(dxfversion="R2018")
        self.msp = self.doc.modelspace()
        self.output_path = output_path

    def draw_wall_polyline(self, x1, y1, x2, y2, thickness_ft, layer):
        self.msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": layer})
        # Note: thickness handled differently in DXF
        return "dxf_entity"  # ezdxf uses different handle system
```

The MCP server detects which driver to use:
```python
def get_driver() -> Union[AutoCADCOMDriver, EzdxfDriver]:
    try:
        driver = AutoCADCOMDriver()
        driver.connect()
        return driver
    except AutoCADNotRunningError:
        logger.warning("AutoCAD not running. Using ezdxf DXF fallback.")
        return EzdxfDriver(output_path=session.dxf_path)
```

---

## AutoCAD Settings Required

For COM automation to work:
1. AutoCAD must be running before `civilengineer design` is called
2. COM automation must be enabled (it is by default in AutoCAD)
3. Security settings must allow external COM connections
   - In AutoCAD: Options → System → ActiveX/COM access → Allow

The `test_autocad.py` smoke test verifies all of this:
```bash
civilengineer test-autocad
  Checking AutoCAD connection...
  ✓ AutoCAD 2024 found and connected
  ✓ New drawing created
  ✓ Layer created: A-WALL-EXTR
  ✓ Test rectangle drawn (20ft × 30ft)
  ✓ Test label added
  ✓ Drawing saved to: C:/Temp/civilengineer_test.dwg
  All tests passed.
```
