"""
MCP element tools — architectural elements (door, window, room label, staircase).

Tools:
  - place_door       Draw a door symbol + swing arc
  - place_window     Draw a window break in a wall
  - add_room_label   Place room name + area text
  - place_staircase  Draw a staircase symbol (flight lines + arrow)
"""

from __future__ import annotations

import logging
import math
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)


def register_element_tools(mcp: FastMCP, get_doc) -> None:
    """Register all architectural element tools on the FastMCP instance."""

    @mcp.tool()
    def place_door(
        x: Annotated[float, Field(description="Door hinge point X (metres)")],
        y: Annotated[float, Field(description="Door hinge point Y (metres)")],
        width: Annotated[float, Field(description="Door leaf width (metres)")] = 0.9,
        angle_deg: Annotated[
            float, Field(description="Wall direction in degrees (0=east, 90=north)")
        ] = 0.0,
        swing_left: Annotated[bool, Field(description="Swing direction left=True")] = True,
        layer: Annotated[str, Field(description="Target layer")] = "A-DOOR",
    ) -> str:
        """
        Place a door symbol: a line for the leaf + a quarter-circle arc for the swing.

        The door hinge is at (x, y). The leaf extends in the wall direction.
        """
        doc = get_doc()
        rad = math.radians(angle_deg)
        swing_sign = 1.0 if swing_left else -1.0

        # Door leaf: line from hinge along wall direction
        leaf_end = (
            x + width * math.cos(rad),
            y + width * math.sin(rad),
            0.0,
        )
        doc.add_line((x, y, 0.0), leaf_end, layer=layer)

        # Swing arc: approximate with 8 line segments (quarter circle)
        arc_pts = []
        for i in range(9):
            theta = math.radians(angle_deg + swing_sign * 90 * i / 8)
            arc_pts.append(
                (x + width * math.cos(theta), y + width * math.sin(theta), 0.0)
            )
        doc.add_polyline(arc_pts, layer=layer, closed=False)

        return f"Door placed at ({x},{y}) width={width}m angle={angle_deg}°"

    @mcp.tool()
    def place_window(
        x: Annotated[float, Field(description="Window centre X (metres)")],
        y: Annotated[float, Field(description="Window centre Y (metres)")],
        width: Annotated[float, Field(description="Window width (metres)")] = 1.2,
        wall_thickness: Annotated[
            float, Field(description="Wall thickness (metres)")
        ] = 0.23,
        angle_deg: Annotated[
            float, Field(description="Wall direction in degrees (0=east, 90=north)")
        ] = 90.0,
        layer: Annotated[str, Field(description="Target layer")] = "A-WIND",
    ) -> str:
        """
        Draw a window symbol: three parallel lines representing the wall break + glazing.

        The symbol is centred at (x, y) with the window perpendicular to `angle_deg`.
        """
        doc = get_doc()
        rad = math.radians(angle_deg)
        perp = math.radians(angle_deg + 90)
        half_w = width / 2
        half_t = wall_thickness / 2

        # Three lines along the wall direction, offset in wall thickness direction
        for offset_t in (-half_t, 0.0, half_t):
            dx = offset_t * math.cos(perp)
            dy = offset_t * math.sin(perp)
            start = (
                x - half_w * math.cos(rad) + dx,
                y - half_w * math.sin(rad) + dy,
                0.0,
            )
            end = (
                x + half_w * math.cos(rad) + dx,
                y + half_w * math.sin(rad) + dy,
                0.0,
            )
            doc.add_line(start, end, layer=layer)

        return f"Window at ({x},{y}) width={width}m on layer {layer}"

    @mcp.tool()
    def add_room_label(
        x: Annotated[float, Field(description="Label X (metres)")],
        y: Annotated[float, Field(description="Label Y (metres)")],
        name: Annotated[str, Field(description="Room name (e.g. 'Master Bedroom')")],
        area_sqm: Annotated[float, Field(description="Room area (sqm)")],
        layer: Annotated[str, Field(description="Target layer")] = "A-ROOM-LABL",
    ) -> str:
        """Place room name (large) and area (small, below) as text entities."""
        doc = get_doc()
        doc.add_text(name, (x, y + 0.12, 0.0), height=0.25, layer=layer)
        doc.add_text(f"{area_sqm:.1f} sqm", (x, y - 0.12, 0.0), height=0.18, layer=layer)
        return f"Room label '{name}' ({area_sqm:.1f} sqm) at ({x},{y})"

    @mcp.tool()
    def place_staircase(
        x: Annotated[float, Field(description="Staircase lower-left X (metres)")],
        y: Annotated[float, Field(description="Staircase lower-left Y (metres)")],
        width: Annotated[float, Field(description="Staircase width (metres)")] = 1.2,
        depth: Annotated[float, Field(description="Staircase depth (metres)")] = 3.6,
        num_treads: Annotated[int, Field(description="Number of treads")] = 14,
        layer: Annotated[str, Field(description="Target layer")] = "A-STAIR",
    ) -> str:
        """
        Draw a staircase symbol: outline rectangle + horizontal tread lines + direction arrow.
        """
        doc = get_doc()

        # Outline
        corners = [
            (x, y, 0.0),
            (x + width, y, 0.0),
            (x + width, y + depth, 0.0),
            (x, y + depth, 0.0),
        ]
        doc.add_polyline(corners, layer=layer, closed=True)

        # Tread lines
        tread_h = depth / num_treads
        for i in range(1, num_treads):
            ty = y + i * tread_h
            doc.add_line((x, ty, 0.0), (x + width, ty, 0.0), layer=layer)

        # Direction arrow (up arrow along centre)
        cx = x + width / 2
        arrow_base_y = y + depth * 0.2
        arrow_tip_y = y + depth * 0.8
        doc.add_line((cx, arrow_base_y, 0.0), (cx, arrow_tip_y, 0.0), layer=layer)
        # Arrowhead
        arrow_w = width * 0.15
        doc.add_line(
            (cx - arrow_w, arrow_tip_y - arrow_w, 0.0),
            (cx, arrow_tip_y, 0.0),
            layer=layer,
        )
        doc.add_line(
            (cx + arrow_w, arrow_tip_y - arrow_w, 0.0),
            (cx, arrow_tip_y, 0.0),
            layer=layer,
        )

        return (
            f"Staircase {width:.1f}×{depth:.1f} m ({num_treads} treads) "
            f"at ({x},{y}) on layer {layer}"
        )
