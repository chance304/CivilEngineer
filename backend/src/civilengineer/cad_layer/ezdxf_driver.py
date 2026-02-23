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

import logging
from datetime import date
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

from civilengineer.cad_layer.layer_manager import LayerManager
from civilengineer.schemas.design import (
    BuildingDesign,
    ColumnPosition,
    Door,
    DoorSwing,
    FloorPlan,
    RoomLayout,
    RoomType,
    WallFace,
    Window,
)
from civilengineer.schemas.mep import ConduitRun, MEPNetwork, PlumbingStack

logger = logging.getLogger(__name__)

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
        self._draw_columns(msp, floor_plan.columns)
        self._draw_north_arrow(msp, building)
        self._draw_title_block(msp, building, floor_plan)
        self._add_dimensions(msp, building, floor_plan)

        # Paper Space layout tab (professional A1 sheet at 1:100)
        self._create_paper_space_layout(doc, floor_plan, building, floor_plan.floor)

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

    # ------------------------------------------------------------------
    # Structural columns
    # ------------------------------------------------------------------

    def _draw_columns(self, msp: Modelspace, columns: list[ColumnPosition]) -> None:
        """Draw structural RCC columns as filled squares (NBC 105 §5.3)."""
        for col in columns:
            pts = [
                (col.x, col.y),
                (col.x + col.width, col.y),
                (col.x + col.width, col.y + col.depth),
                (col.x, col.y + col.depth),
            ]
            # Filled square using SOLID entity (4 points, last repeats first)
            msp.add_solid(
                pts,
                dxfattribs={"layer": LayerManager.COLUMN, "color": 5},
            )
            # Outline for clarity
            msp.add_lwpolyline(
                pts + [pts[0]],
                dxfattribs={"layer": LayerManager.COLUMN},
            )

    # ------------------------------------------------------------------
    # Paper Space layout (A1 sheet, 1:100 scale)
    # ------------------------------------------------------------------

    def _create_paper_space_layout(
        self,
        doc: Drawing,
        floor_plan: FloorPlan,
        building: BuildingDesign,
        floor_num: int,
    ) -> None:
        """
        Create an A1 Paper Space layout tab at nominal 1:100 scale.

        Paper space coordinates are in mm (A1 = 841mm × 594mm).
        The viewport shows the model (in metres) scaled to fit on the sheet.
        The existing modelspace content is preserved for backward compatibility.
        """
        try:
            layout_name = f"Floor {floor_num} Plan"
            # Skip if layout already exists
            existing = [lyt.name for lyt in doc.layouts]
            if layout_name in existing:
                return

            layout = doc.new_layout(layout_name)

            # A1 landscape: 841mm × 594mm
            # Title block occupies bottom 55mm strip
            # Remaining for viewport: 841 × (594 - 55) = 841 × 539mm
            title_height = 55.0   # mm
            margin = 20.0         # mm margins all around
            vp_w = 841.0 - 2 * margin           # ≈ 801mm
            vp_h = 594.0 - title_height - margin  # ≈ 519mm
            vp_cx = 841.0 / 2                    # 420.5mm
            vp_cy = title_height + vp_h / 2      # 55 + 259.5 ≈ 314.5mm

            # Model view height — show full building with 15% margin
            view_h_model = max(
                building.plot_depth,
                floor_plan.buildable_zone.depth,
            ) * 1.15

            vp = layout.add_viewport(
                center=(vp_cx, vp_cy),
                size=(vp_w, vp_h),
                view_center_point=(
                    building.plot_width / 2,
                    building.plot_depth / 2,
                ),
                view_height=view_h_model,
            )
            # Activate viewport (status bit 1 = ON)
            try:
                vp.dxf.status = 1
            except Exception:
                pass  # older ezdxf versions may not support direct status set

            self._draw_paper_title_block(layout, building, floor_num)

        except Exception as exc:
            logger.warning(
                "ezdxf_driver: Paper Space layout creation failed for floor %d: %s",
                floor_num, exc,
            )

    def _draw_paper_title_block(
        self,
        layout: object,
        building: BuildingDesign,
        floor_num: int,
    ) -> None:
        """
        Draw an ISO/AIA-standard title block at the bottom of the A1 sheet.

        All coordinates in mm (paper space).
        """
        # Horizontal strip at bottom: (0, 0) → (841, 55)
        layout.add_lwpolyline(
            [(0, 0), (841, 0), (841, 55), (0, 55), (0, 0)],
            dxfattribs={"layer": LayerManager.TITLE_BLOCK},
        )
        # Vertical divider: separate left fields from right fields
        layout.add_line(
            (550, 0), (550, 55),
            dxfattribs={"layer": LayerManager.TITLE_BLOCK},
        )

        # Left side: project info
        layout.add_text(
            f"Project: {building.project_id}",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": 5,
                "insert": (10, 42),
            },
        )
        layout.add_text(
            f"Floor {floor_num} Plan  —  Jurisdiction: {building.jurisdiction}",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": 7,
                "insert": (10, 28),
            },
        )
        layout.add_text(
            "Scale 1:100   Sheet: A1 Landscape   Units: metres",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": 4,
                "insert": (10, 14),
            },
        )
        layout.add_text(
            "Generated by CivilEngineer AI  |  For review purposes only",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": 3.5,
                "insert": (10, 5),
            },
        )

        # Right side: date and sheet info
        layout.add_text(
            f"Date: {date.today().isoformat()}",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": 4,
                "insert": (560, 42),
            },
        )
        layout.add_text(
            f"Building: {building.plot_width:.1f}m × {building.plot_depth:.1f}m",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": 4,
                "insert": (560, 28),
            },
        )
        layout.add_text(
            f"Floors: {building.num_floors}   Sheet {floor_num} of {building.num_floors}",
            dxfattribs={
                "layer": LayerManager.TITLE_BLOCK,
                "height": 4,
                "insert": (560, 14),
            },
        )

    # ------------------------------------------------------------------
    # MEP drawing methods
    # ------------------------------------------------------------------

    def _draw_mep_electrical(
        self, msp: Modelspace, network: MEPNetwork
    ) -> None:
        """
        Draw electrical conduit runs and panel locations.

        Conduit runs are drawn as polylines on E-CONDUIT (dashed cyan).
        Panel locations are drawn as filled squares on E-PANEL (cyan).
        """
        # Draw conduit runs
        for run in network.conduit_runs:
            if len(run.path) < 2:
                continue
            pts = [(p.x, p.y) for p in run.path]
            msp.add_lwpolyline(
                pts,
                dxfattribs={"layer": LayerManager.MEP_CONDUIT, "ltscale": 0.5},
            )
            # Label the circuit at midpoint
            mid = run.path[len(run.path) // 2]
            msp.add_text(
                f"{run.circuit_name} ({run.wire_gauge_mm2:.1f}mm²)",
                dxfattribs={
                    "layer": LayerManager.MEP_CONDUIT,
                    "height": 0.12,
                    "insert": (mid.x + 0.05, mid.y + 0.05),
                },
            )

        # Draw panels as filled squares (0.3 × 0.3 m)
        for panel in network.panels:
            px, py = panel.location.x, panel.location.y
            half = 0.15
            msp.add_solid(
                [(px - half, py - half), (px + half, py - half),
                 (px - half, py + half), (px + half, py + half)],
                dxfattribs={"layer": LayerManager.MEP_PANEL, "color": 4},
            )
            msp.add_text(
                f"PNL {panel.load_kva:.1f}kVA/{panel.phase}",
                dxfattribs={
                    "layer": LayerManager.MEP_PANEL,
                    "height": 0.15,
                    "insert": (px + 0.20, py - 0.08),
                },
            )

    def _draw_mep_plumbing(
        self, msp: Modelspace, network: MEPNetwork
    ) -> None:
        """
        Draw plumbing stacks and pipe runs.

        Cold supply → P-SUPPLY (blue), hot supply → P-HW-SUPPLY (red),
        stack centre → P-STACK (magenta circle).
        """
        for stack in network.plumbing_stacks:
            # Cold supply path
            if len(stack.cold_pipe_path) >= 2:
                pts = [(p.x, p.y) for p in stack.cold_pipe_path]
                msp.add_lwpolyline(
                    pts,
                    dxfattribs={"layer": LayerManager.MEP_SUPPLY},
                )

            # Hot supply path
            if len(stack.hot_pipe_path) >= 2:
                # Offset hot path 0.05m for legibility
                pts = [(p.x + 0.05, p.y + 0.05) for p in stack.hot_pipe_path]
                msp.add_lwpolyline(
                    pts,
                    dxfattribs={"layer": LayerManager.MEP_HW_SUPPLY},
                )

            # Stack symbol: circle at stack centroid
            if stack.cold_pipe_path:
                sp = stack.cold_pipe_path[0]
                msp.add_circle(
                    (sp.x, sp.y),
                    radius=0.10,
                    dxfattribs={"layer": LayerManager.MEP_STACK},
                )
                msp.add_text(
                    f"STK Ø{stack.pipe_dia_mm:.0f}",
                    dxfattribs={
                        "layer": LayerManager.MEP_STACK,
                        "height": 0.12,
                        "insert": (sp.x + 0.12, sp.y - 0.06),
                    },
                )

    def render_mep_plan(
        self,
        floor_plan: FloorPlan,
        building: BuildingDesign,
        output_path: Path,
    ) -> Drawing:
        """
        Render a separate MEP DXF sheet for a single floor.

        Includes architectural background (faint), conduit runs,
        plumbing stacks, and panel locations.
        """
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = _INSUNITS_METRES
        doc.header["$MEASUREMENT"] = 1

        lm = LayerManager(doc)
        lm.setup_layers()

        msp = doc.modelspace()

        # Faint architectural background
        self._draw_plot_boundary(msp, building)
        self._draw_rooms(msp, floor_plan)

        # MEP content
        if floor_plan.mep_network:
            self._draw_mep_electrical(msp, floor_plan.mep_network)
            self._draw_mep_plumbing(msp, floor_plan.mep_network)

        # Title block (MEP sheet)
        self._draw_title_block(msp, building, floor_plan)

        doc.saveas(output_path)
        logger.info("MEP DXF written: %s", output_path)
        return doc
