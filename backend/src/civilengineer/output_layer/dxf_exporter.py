"""
Multi-floor DXF export utilities.

Supplements the per-floor DXF that draw_node already produces with:
  - Combined layout sheet: all floors tiled side by side in one DXF
  - Site plan: plot boundary + setback lines + building footprint
  - Floor plan index: a title sheet listing all floor numbers and DXF paths

All output is via ezdxf (no AutoCAD required).

Usage
-----
    from civilengineer.output_layer.dxf_exporter import DXFExporter

    exporter = DXFExporter()
    combined = exporter.export_combined(building, output_dir)
    site     = exporter.export_site_plan(building, plot_info, setbacks, output_dir)
"""

from __future__ import annotations

import logging
from pathlib import Path

import ezdxf
from ezdxf.layouts import Modelspace

from civilengineer.cad_layer.layer_manager import LayerManager
from civilengineer.schemas.design import (
    BuildingDesign,
    RoomLayout,
    RoomType,
)

logger = logging.getLogger(__name__)

# DXF INSUNITS = metres
_INSUNITS_METRES = 6

# Gap between floors in the combined sheet (metres)
_FLOOR_GAP = 3.0

# Colours
_ROOM_COLOUR    = 8   # gray
_BOUNDARY_COL   = 3   # green
_SETBACK_COL    = 4   # cyan
_LABEL_COL      = 2   # yellow
_FLOOR_HDR_COL  = 1   # red


class DXFExporter:
    """Export multi-floor DXF drawings and site plan."""

    # ------------------------------------------------------------------ #
    # Combined layout sheet
    # ------------------------------------------------------------------ #

    def export_combined(
        self,
        building: BuildingDesign,
        output_dir: str | Path,
        filename: str = "combined_floors.dxf",
    ) -> Path:
        """
        Create one DXF with every floor plan tiled horizontally.

        Each floor is offset by (plot_width + gap) in X.
        Floor label placed above each tile.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename

        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = _INSUNITS_METRES
        doc.header["$MEASUREMENT"] = 1

        lm = LayerManager(doc)
        lm.setup_layers()

        msp = doc.modelspace()
        tile_width = building.plot_width + _FLOOR_GAP

        for idx, floor_plan in enumerate(sorted(building.floor_plans, key=lambda fp: fp.floor)):
            x_offset = idx * tile_width

            # Floor label
            msp.add_text(
                f"Floor {floor_plan.floor}",
                dxfattribs={
                    "insert": (x_offset + building.plot_width / 2, building.plot_depth + 0.5),
                    "height": 0.5,
                    "layer": LayerManager.ROOM_LABEL,
                    "color": _FLOOR_HDR_COL,
                },
            )

            # Plot boundary
            self._draw_boundary(msp, x_offset, building)

            # Rooms
            for room in floor_plan.rooms:
                self._draw_room(msp, room, x_offset, 0.0)

        doc.saveas(str(path))
        logger.info("Combined DXF saved: %s", path)
        return path

    # ------------------------------------------------------------------ #
    # Site plan
    # ------------------------------------------------------------------ #

    def export_site_plan(
        self,
        building: BuildingDesign,
        plot_info: dict | None,
        setbacks: tuple[float, float, float, float] | None,
        output_dir: str | Path,
        filename: str = "site_plan.dxf",
    ) -> Path:
        """
        Generate a site plan DXF showing:
          - Plot boundary
          - Setback lines (dashed)
          - Ground-floor building footprint (room outlines, floor 1)
          - North arrow
          - Basic plot dimensions
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename

        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = _INSUNITS_METRES
        doc.header["$MEASUREMENT"] = 1

        lm = LayerManager(doc)
        lm.setup_layers()
        msp = doc.modelspace()

        pw = building.plot_width
        pd = building.plot_depth

        # Plot boundary
        self._draw_boundary(msp, 0, building)

        # Setback lines
        if setbacks:
            front, rear, left, right = setbacks
            sb_pts = [
                (left, front),
                (pw - right, front),
                (pw - right, pd - rear),
                (left, pd - rear),
            ]
            pline = msp.add_lwpolyline(sb_pts, dxfattribs={"layer": LayerManager.SETBACK})
            pline.closed = True

        # Ground floor footprint
        ground_fp = next(
            (fp for fp in building.floor_plans if fp.floor == 1),
            None,
        )
        if ground_fp:
            for room in ground_fp.rooms:
                self._draw_room(msp, room, 0.0, 0.0)

        # North arrow (top-right corner)
        self._draw_north_arrow(msp, pw + 1.5, pd - 2.0, north_deg=building.north_direction_deg)

        # Plot dimensions
        msp.add_text(
            f"Plot: {pw:.1f} m × {pd:.1f} m",
            dxfattribs={
                "insert": (pw / 2, -1.5),
                "height": 0.4,
                "layer": LayerManager.DIMENSIONS,
            },
        )

        # North direction label
        msp.add_text(
            f"North: {building.north_direction_deg:.0f}°",
            dxfattribs={
                "insert": (pw / 2, pd + 0.6),
                "height": 0.3,
                "layer": LayerManager.NORTH_ARROW,
            },
        )

        doc.saveas(str(path))
        logger.info("Site plan DXF saved: %s", path)
        return path

    # ------------------------------------------------------------------ #
    # Floor schedule (index DXF)
    # ------------------------------------------------------------------ #

    def export_floor_index(
        self,
        building: BuildingDesign,
        dxf_paths: list[str],
        output_dir: str | Path,
        filename: str = "floor_index.dxf",
    ) -> Path:
        """
        Create a simple floor index sheet listing all floor numbers,
        total room counts, and file paths — useful as a cover sheet.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename

        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = _INSUNITS_METRES
        lm = LayerManager(doc)
        lm.setup_layers()
        msp = doc.modelspace()

        # Title
        msp.add_text(
            f"Project {building.project_id} — Floor Index",
            dxfattribs={"insert": (0, 5 + len(building.floor_plans) * 1.2),
                        "height": 0.5, "layer": LayerManager.TITLE_BLOCK},
        )
        msp.add_text(
            f"Total floors: {building.num_floors}   "
            f"Jurisdiction: {building.jurisdiction}",
            dxfattribs={"insert": (0, 4.8 + len(building.floor_plans) * 1.2),
                        "height": 0.3, "layer": LayerManager.ROOM_LABEL},
        )

        for i, fp in enumerate(sorted(building.floor_plans, key=lambda f: f.floor)):
            y = (len(building.floor_plans) - i) * 1.2
            room_count = len(fp.rooms)
            file_ref = Path(dxf_paths[i]).name if i < len(dxf_paths) else "—"
            msp.add_text(
                f"Floor {fp.floor}   {room_count} rooms   [{file_ref}]",
                dxfattribs={"insert": (0, y), "height": 0.35,
                            "layer": LayerManager.ROOM_LABEL},
            )

        doc.saveas(str(path))
        logger.info("Floor index DXF saved: %s", path)
        return path

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _draw_boundary(msp: Modelspace, x_off: float, building: BuildingDesign) -> None:
        """Draw plot boundary rectangle."""
        pw, pd = building.plot_width, building.plot_depth
        pts = [(x_off, 0), (x_off + pw, 0), (x_off + pw, pd), (x_off, pd)]
        pline = msp.add_lwpolyline(pts, dxfattribs={"layer": LayerManager.PLOT_BOUNDARY})
        pline.closed = True

    @staticmethod
    def _draw_room(
        msp: Modelspace, room: RoomLayout, x_off: float, y_off: float
    ) -> None:
        """Draw a room as a closed polyline + centred label."""
        x1 = room.bounds.x + x_off
        y1 = room.bounds.y + y_off
        x2 = x1 + room.bounds.width
        y2 = y1 + room.bounds.depth

        pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        pline = msp.add_lwpolyline(pts, dxfattribs={"layer": LayerManager.ROOM_OUTLINE})
        pline.closed = True

        # Label: short room name
        short = _SHORT_NAMES.get(room.room_type, room.room_type.value[:4].upper())
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        msp.add_text(
            short,
            dxfattribs={
                "insert": (cx - 0.2, cy),
                "height": min(0.3, room.bounds.width * 0.12),
                "layer": LayerManager.ROOM_LABEL,
            },
        )

    @staticmethod
    def _draw_north_arrow(
        msp: Modelspace, cx: float, cy: float, north_deg: float = 0.0, size: float = 1.0
    ) -> None:
        import math  # noqa: PLC0415
        rad = math.radians(90 - north_deg)
        tip = (cx + size * math.cos(rad), cy + size * math.sin(rad))
        msp.add_line((cx, cy), tip, dxfattribs={"layer": LayerManager.NORTH_ARROW})
        msp.add_text(
            "N",
            dxfattribs={
                "insert": (tip[0] + 0.1, tip[1] + 0.1),
                "height": size * 0.3,
                "layer": LayerManager.NORTH_ARROW,
            },
        )


# Short display names for combined/site DXF labels
_SHORT_NAMES: dict[RoomType, str] = {
    RoomType.MASTER_BEDROOM: "MBR",
    RoomType.BEDROOM:        "BED",
    RoomType.LIVING_ROOM:    "LIV",
    RoomType.DINING_ROOM:    "DIN",
    RoomType.KITCHEN:        "KIT",
    RoomType.BATHROOM:       "BATH",
    RoomType.TOILET:         "WC",
    RoomType.STAIRCASE:      "STAIR",
    RoomType.CORRIDOR:       "CORR",
    RoomType.STORE:          "STR",
    RoomType.POOJA_ROOM:     "POOJA",
    RoomType.GARAGE:         "GAR",
    RoomType.HOME_OFFICE:    "OFFICE",
    RoomType.BALCONY:        "BAL",
    RoomType.TERRACE:        "TER",
}
