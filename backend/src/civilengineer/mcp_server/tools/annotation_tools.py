"""
MCP annotation tools — dimensions, text, title block, north arrow.

Tools:
  - add_linear_dimension   Horizontal or vertical dimension string
  - add_text               Free text entity
  - add_title_block        Project title block (text entries)
  - add_north_arrow        North arrow symbol
"""

from __future__ import annotations

import logging
import math
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)


def register_annotation_tools(mcp: FastMCP, get_doc) -> None:
    """Register all annotation tools on the FastMCP instance."""

    @mcp.tool()
    def add_linear_dimension(
        x1: Annotated[float, Field(description="First extension point X (metres)")],
        y1: Annotated[float, Field(description="First extension point Y (metres)")],
        x2: Annotated[float, Field(description="Second extension point X (metres)")],
        y2: Annotated[float, Field(description="Second extension point Y (metres)")],
        offset: Annotated[
            float, Field(description="Dimension line offset from geometry (metres)")
        ] = 0.8,
        layer: Annotated[str, Field(description="Target layer")] = "A-ANNO-DIMS",
    ) -> str:
        """
        Draw a linear dimension string between two points.

        Approximated using lines and text (ezdxf dimension entity used when available).
        """
        doc = get_doc()
        distance = math.hypot(x2 - x1, y2 - y1)
        is_horizontal = abs(y2 - y1) < abs(x2 - x1)

        if is_horizontal:
            # Dimension line below (or above) both points
            dy_off = -offset if y1 <= y2 else offset
            dl_y = y1 + dy_off
            doc.add_line((x1, dl_y, 0.0), (x2, dl_y, 0.0), layer=layer)
            doc.add_line((x1, y1, 0.0), (x1, dl_y, 0.0), layer=layer)
            doc.add_line((x2, y2, 0.0), (x2, dl_y, 0.0), layer=layer)
            cx = (x1 + x2) / 2
            doc.add_text(
                f"{distance:.2f} m",
                (cx, dl_y + 0.1, 0.0),
                height=0.20,
                layer=layer,
            )
        else:
            dx_off = -offset
            dl_x = x1 + dx_off
            doc.add_line((dl_x, y1, 0.0), (dl_x, y2, 0.0), layer=layer)
            doc.add_line((x1, y1, 0.0), (dl_x, y1, 0.0), layer=layer)
            doc.add_line((x2, y2, 0.0), (dl_x, y2, 0.0), layer=layer)
            cy = (y1 + y2) / 2
            doc.add_text(
                f"{distance:.2f} m",
                (dl_x - 0.25, cy, 0.0),
                height=0.20,
                layer=layer,
            )

        return (
            f"Dimension {distance:.2f} m from ({x1},{y1}) to ({x2},{y2}), "
            f"offset {offset} m on layer {layer}"
        )

    @mcp.tool()
    def add_text(
        text: Annotated[str, Field(description="Text content")],
        x: Annotated[float, Field(description="Insertion point X (metres)")],
        y: Annotated[float, Field(description="Insertion point Y (metres)")],
        height: Annotated[float, Field(description="Text height (metres)")] = 0.25,
        layer: Annotated[str, Field(description="Target layer")] = "A-ANNO-TITL",
    ) -> str:
        """Place a text entity at the specified location."""
        doc = get_doc()
        doc.add_text(text, (x, y, 0.0), height=height, layer=layer)
        return f"Text '{text}' at ({x},{y}) h={height} on layer {layer}"

    @mcp.tool()
    def add_title_block(
        project_name: Annotated[str, Field(description="Project name")],
        client_name: Annotated[str, Field(description="Client name")],
        drawing_title: Annotated[str, Field(description="Drawing title (e.g. 'Ground Floor Plan')")],
        scale: Annotated[str, Field(description="Drawing scale (e.g. '1:100')")] = "1:100",
        drawn_by: Annotated[str, Field(description="Drafter name / initials")] = "AI Copilot",
        sheet_no: Annotated[str, Field(description="Sheet number (e.g. 'A-01')")] = "A-01",
        x: Annotated[float, Field(description="Title block lower-left X (metres)")] = 0.0,
        y: Annotated[float, Field(description="Title block lower-left Y (metres)")] = -3.0,
        layer: Annotated[str, Field(description="Target layer")] = "A-ANNO-TITL",
    ) -> str:
        """
        Place a standard title block with project information.

        The title block is drawn as text lines. A border rectangle is also drawn.
        """
        doc = get_doc()
        w, h = 20.0, 2.5

        # Border
        corners = [
            (x, y, 0.0),
            (x + w, y, 0.0),
            (x + w, y + h, 0.0),
            (x, y + h, 0.0),
        ]
        doc.add_polyline(corners, layer=layer, closed=True)

        # Text fields
        entries = [
            (f"PROJECT: {project_name}", 0.40, 0.35),
            (f"CLIENT: {client_name}",   0.40, 0.20),
            (drawing_title,               10.0, 0.35),
            (f"SCALE: {scale}",           15.0, 0.35),
            (f"DRAWN: {drawn_by}",        15.0, 0.20),
            (f"SHEET: {sheet_no}",        18.0, 0.35),
        ]
        for text, dx, dy in entries:
            doc.add_text(text, (x + dx, y + dy, 0.0), height=0.20, layer=layer)

        return f"Title block at ({x},{y}) for '{project_name}' — {drawing_title}"

    @mcp.tool()
    def add_north_arrow(
        x: Annotated[float, Field(description="Arrow centre X (metres)")],
        y: Annotated[float, Field(description="Arrow centre Y (metres)")],
        north_deg: Annotated[
            float, Field(description="North direction in degrees (0=up, 90=right)")
        ] = 0.0,
        size: Annotated[float, Field(description="Arrow size (metres)")] = 1.0,
        layer: Annotated[str, Field(description="Target layer")] = "A-ANNO-NRTH",
    ) -> str:
        """
        Draw a north arrow symbol at the specified location.

        The arrow points toward true north as defined by `north_deg`.
        """
        doc = get_doc()
        # Arrow shaft
        rad = math.radians(90 - north_deg)  # convert to mathematical angle
        tip = (
            x + size * math.cos(rad),
            y + size * math.sin(rad),
            0.0,
        )
        doc.add_line((x, y, 0.0), tip, layer=layer)

        # Arrowhead (two lines)
        head_size = size * 0.25
        left_rad  = rad - math.radians(30)
        right_rad = rad + math.radians(30)
        doc.add_line(
            tip,
            (
                tip[0] - head_size * math.cos(left_rad),
                tip[1] - head_size * math.sin(left_rad),
                0.0,
            ),
            layer=layer,
        )
        doc.add_line(
            tip,
            (
                tip[0] - head_size * math.cos(right_rad),
                tip[1] - head_size * math.sin(right_rad),
                0.0,
            ),
            layer=layer,
        )

        # "N" label near tip
        doc.add_text(
            "N",
            (tip[0] + 0.1, tip[1] + 0.1, 0.0),
            height=size * 0.3,
            layer=layer,
        )

        return f"North arrow at ({x},{y}) pointing {north_deg}° on layer {layer}"
