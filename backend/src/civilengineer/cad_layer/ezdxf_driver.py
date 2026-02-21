"""
ezdxf-based DXF floor plan generator.

Converts a FloorPlan (room bounds, doors, windows) into a professional DXF file
with AIA-standard layers, room labels, dimension annotations, north arrow,
plot boundary, and setback reference lines.

All coordinates are in metres. The DXF INSUNITS is set to 6 (metres).

Usage:
    driver = EzdxfDriver()
    doc = driver.render_floor_plan(floor_plan, building_design, output_path)
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

from civilengineer.cad_layer.layer_manager import LayerManager
from civilengineer.schemas.design import (
    BuildingDesign,
    Door,
    DoorSwing,
    FloorPlan,
    RoomLayout,
    RoomType,
    WallFace,
    Window,
)

# DXF INSUNITS value for metres
_INSUNITS_METRES = 6


class EzdxfDriver:
    """Generates DXF floor plan drawings from FloorPlan data."""

    # Text heights in metres
    ROOM_LABEL_HEIGHT = 0.25
    AREA_LABEL_HEIGHT = 0.18
    DIM_TEXT_HEIGHT = 0.20
    TITLE_TEXT_HEIGHT = 0.40

    # Wall thickness in metres (drawn as lwpolyline with width)
    WALL_THICKNESS = 0.23

    def render_floor_plan(
        self,
        floor_plan: FloorPlan,
        building: BuildingDesign,
        output_path: Path,
    ) -> Drawing:
        """
        Render a single floor plan to a DXF file.

        Returns the ezdxf Drawing object (also written to output_path).
        """
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = _INSUNITS_METRES
        doc.header["$MEASUREMENT"] = 1  # metric

        lm = LayerManager(doc)
        lm.setup_layers()

        msp = doc.modelspace()

        self._draw_plot_boundary(msp, building)
        self._draw_setbacks(msp, building, floor_plan)
        self._draw_rooms(msp, floor_plan)
        self._draw_north_arrow(msp, building)
        self._draw_title_block(msp, building, floor_plan)
        self._add_dimensions(msp, building, floor_plan)

        doc.saveas(output_path)
        return doc

    # ------------------------------------------------------------------
    # Plot boundary
    # ------------------------------------------------------------------

    def _draw_plot_boundary(self, msp: Modelspace, building: BuildingDesign) -> None:
        pts = [
            (0.0, 0.0),
            (building.plot_width, 0.0),
            (building.plot_width, building.plot_depth),
            (0.0, building.plot_depth),
            (0.0, 0.0),
        ]
        msp.add_lwpolyline(
            pts,
            dxfattribs={"layer": LayerManager.PLOT_BOUNDARY, "lineweight": 50},
        )

    # ------------------------------------------------------------------
    # Setback lines
    # ------------------------------------------------------------------

    def _draw_setbacks(
        self, msp: Modelspace, building: BuildingDesign, floor_plan: FloorPlan
    ) -> None:
        bz = floor_plan.buildable_zone
        sb_pts = [
            (bz.x, bz.y),
            (bz.x + bz.width, bz.y),
            (bz.x + bz.width, bz.y + bz.depth),
            (bz.x, bz.y + bz.depth),
            (bz.x, bz.y),
        ]
        msp.add_lwpolyline(
            sb_pts,
            dxfattribs={"layer": LayerManager.SETBACK, "linetype": "DASHED"},
        )
        # Setback dimension text (front setback)
        mid_x = bz.x + bz.width / 2
        msp.add_text(
            f"Setback {building.setback_front:.1f}m",
            dxfattribs={
                "layer": LayerManager.DIMENSIONS,
                "height": self.DIM_TEXT_HEIGHT * 0.8,
                "insert": (mid_x, bz.y / 2),
                "halign": 1,
                "valign": 0,
            },
        )

    # ------------------------------------------------------------------
    # Rooms (walls, labels, doors, windows)
    # ------------------------------------------------------------------

    def _draw_rooms(self, msp: Modelspace, floor_plan: FloorPlan) -> None:
        for room in floor_plan.rooms:
            self._draw_room_walls(msp, room)
            self._draw_room_label(msp, room)
            for door in room.doors:
                self._draw_door(msp, room, door)
            for window in room.windows:
                self._draw_window(msp, room, window)

    def _draw_room_walls(self, msp: Modelspace, room: RoomLayout) -> None:
        b = room.bounds
        layer = (
            LayerManager.WALL_EXT
            if (
                room.is_external_wall_north
                or room.is_external_wall_south
                or room.is_external_wall_east
                or room.is_external_wall_west
            )
            else LayerManager.WALL_INT_LOAD
        )
        if room.room_type == RoomType.STAIRCASE:
            layer = LayerManager.STAIR

        pts = [
            (b.x, b.y),
            (b.x + b.width, b.y),
            (b.x + b.width, b.y + b.depth),
            (b.x, b.y + b.depth),
            (b.x, b.y),
        ]
        poly = msp.add_lwpolyline(
            pts,
            dxfattribs={"layer": layer},
        )
        poly.dxf.const_width = self.WALL_THICKNESS / 2

    def _draw_room_label(self, msp: Modelspace, room: RoomLayout) -> None:
        cx = room.bounds.x + room.bounds.width / 2
        cy = room.bounds.y + room.bounds.depth / 2

        # Room type name (bold via height)
        msp.add_text(
            room.name,
            dxfattribs={
                "layer": LayerManager.ROOM_LABEL,
                "height": self.ROOM_LABEL_HEIGHT,
                "insert": (cx, cy + self.ROOM_LABEL_HEIGHT * 0.6),
                "halign": 4,   # middle center
                "valign": 0,
            },
        )
        # Area below
        msp.add_text(
            f"{room.area:.1f} m²",
            dxfattribs={
                "layer": LayerManager.ROOM_LABEL,
                "height": self.AREA_LABEL_HEIGHT,
                "insert": (cx, cy - self.AREA_LABEL_HEIGHT),
                "halign": 4,
                "valign": 0,
            },
        )

    def _draw_door(self, msp: Modelspace, room: RoomLayout, door: Door) -> None:
        b = room.bounds
        pos = door.position_along_wall
        w = door.width
        # Determine door hinge point and swing direction based on wall face
        if door.wall_face == WallFace.SOUTH:
            hinge = (b.x + pos, b.y)
            end = (b.x + pos + w, b.y)
            arc_center = hinge if door.swing == DoorSwing.RIGHT else end
            arc_start = 0 if door.swing == DoorSwing.RIGHT else 180
        elif door.wall_face == WallFace.NORTH:
            hinge = (b.x + pos, b.y + b.depth)
            end = (b.x + pos + w, b.y + b.depth)
            arc_center = hinge if door.swing == DoorSwing.RIGHT else end
            arc_start = 0 if door.swing == DoorSwing.RIGHT else 180
        elif door.wall_face == WallFace.WEST:
            hinge = (b.x, b.y + pos)
            end = (b.x, b.y + pos + w)
            arc_center = hinge if door.swing == DoorSwing.RIGHT else end
            arc_start = 90 if door.swing == DoorSwing.RIGHT else 270
        else:  # EAST
            hinge = (b.x + b.width, b.y + pos)
            end = (b.x + b.width, b.y + pos + w)
            arc_center = hinge if door.swing == DoorSwing.RIGHT else end
            arc_start = 90 if door.swing == DoorSwing.RIGHT else 270

        # Door leaf line
        msp.add_line(hinge, end, dxfattribs={"layer": LayerManager.DOOR})
        # Swing arc (quarter circle)
        msp.add_arc(
            center=arc_center,
            radius=w,
            start_angle=arc_start,
            end_angle=arc_start + 90,
            dxfattribs={"layer": LayerManager.DOOR},
        )

    def _draw_window(self, msp: Modelspace, room: RoomLayout, window: Window) -> None:
        b = room.bounds
        pos = window.position_along_wall
        w = window.width
        # Draw three parallel lines to indicate glazing
        if window.wall_face == WallFace.SOUTH:
            y = b.y
            for offset in [0.0, 0.06, 0.12]:
                msp.add_line(
                    (b.x + pos, y + offset),
                    (b.x + pos + w, y + offset),
                    dxfattribs={"layer": LayerManager.WINDOW},
                )
        elif window.wall_face == WallFace.NORTH:
            y = b.y + b.depth
            for offset in [0.0, -0.06, -0.12]:
                msp.add_line(
                    (b.x + pos, y + offset),
                    (b.x + pos + w, y + offset),
                    dxfattribs={"layer": LayerManager.WINDOW},
                )
        elif window.wall_face == WallFace.WEST:
            x = b.x
            for offset in [0.0, 0.06, 0.12]:
                msp.add_line(
                    (x + offset, b.y + pos),
                    (x + offset, b.y + pos + w),
                    dxfattribs={"layer": LayerManager.WINDOW},
                )
        else:  # EAST
            x = b.x + b.width
            for offset in [0.0, -0.06, -0.12]:
                msp.add_line(
                    (x + offset, b.y + pos),
                    (x + offset, b.y + pos + w),
                    dxfattribs={"layer": LayerManager.WINDOW},
                )

    # ------------------------------------------------------------------
    # North arrow
    # ------------------------------------------------------------------

    def _draw_north_arrow(self, msp: Modelspace, building: BuildingDesign) -> None:
        # Place in upper-right of plot + margin
        origin_x = building.plot_width + 1.5
        origin_y = building.plot_depth - 2.0
        length = 1.2

        # Arrow shaft
        msp.add_line(
            (origin_x, origin_y),
            (origin_x, origin_y + length),
            dxfattribs={"layer": LayerManager.NORTH_ARROW},
        )
        # Arrowhead (filled triangle)
        msp.add_solid(
            [
                (origin_x, origin_y + length),
                (origin_x - 0.2, origin_y + length - 0.4),
                (origin_x + 0.2, origin_y + length - 0.4),
                (origin_x, origin_y + length),
            ],
            dxfattribs={"layer": LayerManager.NORTH_ARROW, "color": 7},
        )
        # "N" label
        msp.add_text(
            "N",
            dxfattribs={
                "layer": LayerManager.NORTH_ARROW,
                "height": 0.35,
                "insert": (origin_x, origin_y + length + 0.15),
                "halign": 4,
                "valign": 0,
            },
        )

    # ------------------------------------------------------------------
    # Title block
    # ------------------------------------------------------------------

    def _draw_title_block(
        self, msp: Modelspace, building: BuildingDesign, floor_plan: FloorPlan
    ) -> None:
        # Simple title block below the plot
        tb_x = 0.0
        tb_y = -3.5
        tb_w = building.plot_width
        tb_h = 3.0

        # Border
        pts = [
            (tb_x, tb_y),
            (tb_x + tb_w, tb_y),
            (tb_x + tb_w, tb_y + tb_h),
            (tb_x, tb_y + tb_h),
            (tb_x, tb_y),
        ]
        msp.add_lwpolyline(pts, dxfattribs={"layer": LayerManager.TITLE_BLOCK})

        title = f"Floor Plan — Floor {floor_plan.floor}"
        msp.add_text(
            title,
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": self.TITLE_TEXT_HEIGHT,
                "insert": (tb_x + tb_w / 2, tb_y + tb_h - 0.7),
                "halign": 4,
                "valign": 0,
            },
        )
        msp.add_text(
            f"Project: {building.project_id}   Jurisdiction: {building.jurisdiction}",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": self.DIM_TEXT_HEIGHT,
                "insert": (tb_x + tb_w / 2, tb_y + tb_h - 1.3),
                "halign": 4,
                "valign": 0,
            },
        )
        msp.add_text(
            "Scale: 1:100   Units: metres",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": self.DIM_TEXT_HEIGHT,
                "insert": (tb_x + tb_w / 2, tb_y + tb_h - 1.9),
                "halign": 4,
                "valign": 0,
            },
        )

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------

    def _add_dimensions(
        self, msp: Modelspace, building: BuildingDesign, floor_plan: FloorPlan
    ) -> None:
        """Add overall plot width and depth dimension annotations."""
        dimstyle = "Standard"

        # Width dimension (below plot boundary)
        dim_y = -0.8
        msp.add_linear_dim(
            base=(building.plot_width / 2, dim_y),
            p1=(0.0, 0.0),
            p2=(building.plot_width, 0.0),
            angle=0,
            dimstyle=dimstyle,
            override={"dimtxt": self.DIM_TEXT_HEIGHT, "dimclrd": 8, "dimclrt": 8},
            dxfattribs={"layer": LayerManager.DIMENSIONS},
        )

        # Depth dimension (to the right of plot boundary)
        dim_x = building.plot_width + 0.8
        msp.add_linear_dim(
            base=(dim_x, building.plot_depth / 2),
            p1=(building.plot_width, 0.0),
            p2=(building.plot_width, building.plot_depth),
            angle=90,
            dimstyle=dimstyle,
            override={"dimtxt": self.DIM_TEXT_HEIGHT, "dimclrd": 8, "dimclrt": 8},
            dxfattribs={"layer": LayerManager.DIMENSIONS},
        )
