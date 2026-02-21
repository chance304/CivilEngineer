"""
Phase 1 smoke test — Core CAD pipeline.

Generates DXF floor plans (all floors) + elevation views (all 4 faces) +
3D building outline from a hardcoded 2-floor residential layout.

Hardcoded test project:
    Plot:        10m × 12m, north-facing
    Jurisdiction: NP-KTM (Kathmandu Metropolitan City)
    Road width:   6m → front setback 3.0m, others 1.5m
    Buildable:    7.0m wide × 7.5m deep
    Floor 1:     Living Room, Kitchen, Staircase, WC
    Floor 2:     Master Bedroom, Bedroom 2, Staircase (same position), Bathroom
    Floor height: 3.0m per floor

Success criterion (from Phase 1 roadmap):
    python scripts/test_cad.py
    → produces test_floor_plan_F1.dxf, test_floor_plan_F2.dxf,
      test_elevation_front.dxf, test_elevation_rear.dxf,
      test_elevation_left.dxf, test_elevation_right.dxf,
      test_building_3d.dxf
    All files open in any DXF viewer with correct layers, dimensions, labels.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import ezdxf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from civilengineer.cad_layer.ezdxf_driver import EzdxfDriver
from civilengineer.elevation_engine.building_3d import Building3DGenerator
from civilengineer.elevation_engine.elevation_generator import ElevationGenerator
from civilengineer.schemas.design import (
    BuildingDesign,
    Door,
    DoorSwing,
    FloorPlan,
    Rect2D,
    RoomLayout,
    RoomType,
    WallFace,
    Window,
)
from civilengineer.schemas.elevation import ElevationFace

console = Console()

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Hardcoded test layout
# ---------------------------------------------------------------------------

def build_test_design() -> BuildingDesign:
    """
    Construct the hardcoded 2-floor test layout.

    Plot: 10m × 12m, origin at (0,0)
    Buildable zone origin: (1.5, 3.0) — left/right setback 1.5m, front 3.0m
    Buildable zone size:   7.0m × 7.5m
    """
    plot_width = 10.0
    plot_depth = 12.0
    setback_front = 3.0   # from south edge (south = road, north = back)
    setback_rear  = 1.5
    setback_left  = 1.5
    setback_right = 1.5

    # Buildable zone: south face is at y=setback_front (road is at y=0)
    bz = Rect2D(
        x=setback_left,
        y=setback_front,
        width=plot_width - setback_left - setback_right,   # 7.0m
        depth=plot_depth - setback_front - setback_rear,   # 7.5m
    )

    # ------------------------------------------------------------------
    # Floor 1 rooms (placed within buildable zone)
    # Layout (looking from above, north = top):
    #
    #   ┌──────────────────┐  y = bz.y + bz.depth = 10.5
    #   │  Staircase       │  x: 1.5–4.5, y: 7.0–10.5
    #   │  3.0 × 3.5       │
    #   ├───────┬──────────┤  y = 7.0
    #   │Kitchen│  WC      │
    #   │2.5×4  │  4.0×3.5 │  y: 3.0–7.0
    #   ├───────┘          │
    #   │  Living Room     │
    #   │  4.5 × 4.0       │  y: 3.0–7.0
    #   └──────────────────┘  y = bz.y = 3.0
    #   x: 1.5             8.5
    #
    # Simplified: 2-column layout
    # Col A (x: 1.5–6.0, width 4.5):
    #   Living Room (y: 3.0 – 7.0, 4.5×4.0)
    #   Staircase   (y: 7.0 – 10.5, 3.0×3.5) — shares col A left portion
    # Col B (x: 6.0–8.5, width 2.5):
    #   Kitchen     (y: 3.0 – 7.0, 2.5×4.0)
    #   WC          (y: 7.0 – 10.5, 2.5×3.5)
    # ------------------------------------------------------------------

    bz_x = bz.x   # 1.5
    bz_y = bz.y   # 3.0

    living_room = RoomLayout(
        room_id="F1-LIVING",
        room_type=RoomType.LIVING_ROOM,
        name="Living Room",
        floor=1,
        bounds=Rect2D(x=bz_x, y=bz_y, width=4.5, depth=4.0),
        doors=[
            Door(
                wall_face=WallFace.SOUTH,
                position_along_wall=1.5,
                width=1.0,
                swing=DoorSwing.LEFT,
                is_main_entrance=True,
            )
        ],
        windows=[
            Window(wall_face=WallFace.SOUTH, position_along_wall=3.0, width=1.5),
            Window(wall_face=WallFace.WEST,  position_along_wall=1.0, width=1.2),
        ],
        is_external_wall_south=True,
        is_external_wall_west=True,
    )

    kitchen = RoomLayout(
        room_id="F1-KITCHEN",
        room_type=RoomType.KITCHEN,
        name="Kitchen",
        floor=1,
        bounds=Rect2D(x=bz_x + 4.5, y=bz_y, width=2.5, depth=4.0),
        doors=[
            Door(wall_face=WallFace.WEST, position_along_wall=1.2, width=0.9)
        ],
        windows=[
            Window(wall_face=WallFace.SOUTH, position_along_wall=0.5, width=1.0),
            Window(wall_face=WallFace.EAST,  position_along_wall=1.0, width=1.0),
        ],
        is_external_wall_south=True,
        is_external_wall_east=True,
    )

    staircase_f1 = RoomLayout(
        room_id="F1-STAIR",
        room_type=RoomType.STAIRCASE,
        name="Staircase",
        floor=1,
        bounds=Rect2D(x=bz_x, y=bz_y + 4.0, width=3.0, depth=3.5),
        doors=[
            Door(wall_face=WallFace.SOUTH, position_along_wall=1.0, width=0.9)
        ],
        is_external_wall_west=True,
    )

    wc_f1 = RoomLayout(
        room_id="F1-WC",
        room_type=RoomType.TOILET,
        name="WC",
        floor=1,
        bounds=Rect2D(x=bz_x + 4.5, y=bz_y + 4.0, width=2.5, depth=3.5),
        doors=[
            Door(wall_face=WallFace.WEST, position_along_wall=0.8, width=0.75)
        ],
        windows=[
            Window(wall_face=WallFace.EAST, position_along_wall=0.5, width=0.6, height=0.6, sill_height=1.5),
            Window(wall_face=WallFace.NORTH, position_along_wall=0.5, width=0.6, height=0.6, sill_height=1.5),
        ],
        is_external_wall_east=True,
        is_external_wall_north=True,
    )

    # ------------------------------------------------------------------
    # Floor 2 rooms — staircase at exact same x,y as floor 1
    # Col A: Master Bedroom + Staircase
    # Col B: Bedroom 2 + Bathroom
    # ------------------------------------------------------------------

    master_bedroom = RoomLayout(
        room_id="F2-MASTER",
        room_type=RoomType.MASTER_BEDROOM,
        name="Master Bedroom",
        floor=2,
        bounds=Rect2D(x=bz_x, y=bz_y, width=4.5, depth=4.0),
        doors=[
            Door(wall_face=WallFace.EAST, position_along_wall=3.0, width=0.9)
        ],
        windows=[
            Window(wall_face=WallFace.SOUTH, position_along_wall=1.0, width=1.5),
            Window(wall_face=WallFace.WEST,  position_along_wall=1.0, width=1.2),
        ],
        is_external_wall_south=True,
        is_external_wall_west=True,
    )

    bedroom2 = RoomLayout(
        room_id="F2-BED2",
        room_type=RoomType.BEDROOM,
        name="Bedroom 2",
        floor=2,
        bounds=Rect2D(x=bz_x + 4.5, y=bz_y, width=2.5, depth=4.0),
        doors=[
            Door(wall_face=WallFace.WEST, position_along_wall=0.5, width=0.9)
        ],
        windows=[
            Window(wall_face=WallFace.SOUTH, position_along_wall=0.5, width=1.0),
            Window(wall_face=WallFace.EAST,  position_along_wall=1.0, width=1.0),
        ],
        is_external_wall_south=True,
        is_external_wall_east=True,
    )

    staircase_f2 = RoomLayout(
        room_id="F2-STAIR",
        room_type=RoomType.STAIRCASE,
        name="Staircase",
        floor=2,
        # Same position as F1 staircase (staircase continuity)
        bounds=Rect2D(x=bz_x, y=bz_y + 4.0, width=3.0, depth=3.5),
        doors=[
            Door(wall_face=WallFace.EAST, position_along_wall=1.0, width=0.9)
        ],
        is_external_wall_west=True,
        is_external_wall_north=True,
    )

    bathroom = RoomLayout(
        room_id="F2-BATH",
        room_type=RoomType.BATHROOM,
        name="Bathroom",
        floor=2,
        bounds=Rect2D(x=bz_x + 4.5, y=bz_y + 4.0, width=2.5, depth=3.5),
        doors=[
            Door(wall_face=WallFace.WEST, position_along_wall=0.8, width=0.75)
        ],
        windows=[
            Window(wall_face=WallFace.EAST,  position_along_wall=0.5, width=0.6, height=0.6, sill_height=1.5),
            Window(wall_face=WallFace.NORTH, position_along_wall=0.5, width=0.6, height=0.6, sill_height=1.5),
        ],
        is_external_wall_east=True,
        is_external_wall_north=True,
    )

    # ------------------------------------------------------------------
    # Assemble floor plans
    # ------------------------------------------------------------------

    floor1 = FloorPlan(
        floor=1,
        floor_height=3.0,
        buildable_zone=bz,
        rooms=[living_room, kitchen, staircase_f1, wc_f1],
    )

    floor2 = FloorPlan(
        floor=2,
        floor_height=3.0,
        buildable_zone=bz,
        rooms=[master_bedroom, bedroom2, staircase_f2, bathroom],
    )

    building = BuildingDesign(
        design_id="TEST-001",
        project_id="TEST-PROJECT-001",
        jurisdiction="NP-KTM",
        num_floors=2,
        plot_width=plot_width,
        plot_depth=plot_depth,
        north_direction_deg=0.0,
        floor_plans=[floor1, floor2],
        setback_front=setback_front,
        setback_rear=setback_rear,
        setback_left=setback_left,
        setback_right=setback_right,
    )

    return building


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_dxf(path: Path) -> tuple[bool, str]:
    """Verify that the DXF file can be re-read by ezdxf without errors."""
    try:
        doc = ezdxf.readfile(str(path))
        entity_count = len(list(doc.modelspace()))
        return True, f"{entity_count} entities"
    except Exception as e:
        return False, str(e)


def check_layers_present(path: Path, required_layers: list[str]) -> list[str]:
    """Return any required layers that are missing from the DXF."""
    doc = ezdxf.readfile(str(path))
    present = {layer.dxf.name for layer in doc.layers}
    return [l for l in required_layers if l not in present]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    console.print(Panel.fit(
        "[bold cyan]Phase 1 — CAD Pipeline Smoke Test[/bold cyan]\n"
        "Generates floor plan DXFs + elevation DXFs + 3D outline DXF",
        title="CivilEngineer",
    ))

    # Build the test layout
    console.print("\n[bold]Building test layout...[/bold]")
    building = build_test_design()
    console.print(
        f"  Plot: {building.plot_width}m × {building.plot_depth}m  |  "
        f"Floors: {building.num_floors}  |  "
        f"Jurisdiction: {building.jurisdiction}"
    )

    driver = EzdxfDriver()
    elev_gen = ElevationGenerator()
    bldg_3d = Building3DGenerator()

    results: list[tuple[str, bool, str]] = []

    # ------------------------------------------------------------------
    # 1. Floor plan DXFs
    # ------------------------------------------------------------------
    console.print("\n[bold]Generating floor plan DXFs...[/bold]")

    floor_plan_layers = [
        "A-WALL-EXTR", "A-WALL-INT-LOAD", "A-DOOR", "A-WIND",
        "A-ROOM-LABL", "C-PLOT", "C-SETB", "A-ANNO-DIMS",
    ]

    for fp in sorted(building.floor_plans, key=lambda f: f.floor):
        fname = OUTPUT_DIR / f"test_floor_plan_F{fp.floor}.dxf"
        console.print(f"  Rendering Floor {fp.floor} → {fname.name}")
        driver.render_floor_plan(fp, building, fname)

        ok, detail = validate_dxf(fname)
        missing = check_layers_present(fname, floor_plan_layers)
        status = ok and not missing
        msg = detail if ok else detail
        if missing:
            msg += f"  [MISSING LAYERS: {missing}]"
        results.append((fname.name, status, msg))

    # ------------------------------------------------------------------
    # 2. Elevation DXFs
    # ------------------------------------------------------------------
    console.print("\n[bold]Generating elevation views...[/bold]")
    elevation_set = elev_gen.generate_elevation_set(building)

    elev_layers = ["A-ELEV-OUTL", "A-ELEV-DETL", "A-ELEV-ANNO"]
    face_order = [
        (ElevationFace.FRONT, "front"),
        (ElevationFace.REAR,  "rear"),
        (ElevationFace.LEFT,  "left"),
        (ElevationFace.RIGHT, "right"),
    ]

    for face, face_name in face_order:
        view = elevation_set.get_face(face)
        if view is None:
            continue
        fname = OUTPUT_DIR / f"test_elevation_{face_name}.dxf"
        console.print(
            f"  Rendering {view.north_label} ({view.face_width:.1f}m wide, "
            f"{view.total_height:.2f}m tall) → {fname.name}"
        )
        elev_gen.render_elevation_dxf(view, fname, building)

        ok, detail = validate_dxf(fname)
        missing = check_layers_present(fname, elev_layers)
        status = ok and not missing
        msg = detail
        if missing:
            msg += f"  [MISSING LAYERS: {missing}]"
        results.append((fname.name, status, msg))

    # ------------------------------------------------------------------
    # 3. 3D building outline DXF
    # ------------------------------------------------------------------
    console.print("\n[bold]Generating 3D building outline...[/bold]")
    outline = bldg_3d.generate_outline(building)
    fname_3d = OUTPUT_DIR / "test_building_3d.dxf"
    console.print(
        f"  Wireframe: {len(outline.vertices)} vertices, "
        f"{len(outline.edges)} edges → {fname_3d.name}"
    )
    bldg_3d.render_dxf(outline, fname_3d)

    ok, detail = validate_dxf(fname_3d)
    results.append((fname_3d.name, ok, detail))

    # ------------------------------------------------------------------
    # Results table
    # ------------------------------------------------------------------
    console.print()
    table = Table(title="Results", show_header=True, header_style="bold")
    table.add_column("File", style="cyan")
    table.add_column("Status")
    table.add_column("Detail", style="dim")

    all_passed = True
    for name, ok, detail in results:
        status_str = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        if not ok:
            all_passed = False
        table.add_row(name, status_str, detail)

    console.print(table)

    if all_passed:
        console.print(Panel.fit(
            "[bold green]All files generated and validated successfully![/bold green]\n"
            f"Output directory: {OUTPUT_DIR}",
            title="Phase 1 PASSED",
            border_style="green",
        ))
        return 0
    else:
        console.print(Panel.fit(
            "[bold red]One or more files failed validation.[/bold red]",
            title="Phase 1 FAILED",
            border_style="red",
        ))
        return 1


if __name__ == "__main__":
    sys.exit(main())
