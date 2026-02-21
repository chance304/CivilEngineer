"""
MCP file tools — save, export, layer management.

Tools:
  - save_drawing        Save the active drawing to DXF/DWG
  - set_layer_visible   Toggle layer visibility
  - list_layers         List all layers in the active drawing
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)


def register_file_tools(mcp: FastMCP, get_doc) -> None:
    """Register all file management tools on the FastMCP instance."""

    @mcp.tool()
    def save_drawing(
        path: Annotated[str, Field(description="Output file path (.dxf or .dwg)")],
    ) -> str:
        """
        Save the active drawing to disk.

        On Linux / without AutoCAD: always saves as .dxf (AutoCAD fallback).
        On Windows with AutoCAD: saves as .dwg (native format).
        """
        doc = get_doc()
        saved_path = doc.save(path)
        return f"Drawing saved to {saved_path}"

    @mcp.tool()
    def setup_layers(
        all_standard: Annotated[
            bool,
            Field(description="Create all AIA-standard layers"),
        ] = True,
    ) -> str:
        """
        Create AIA-standard layers (A-WALL-EXTR, A-DOOR, A-WIND, etc.)
        in the active drawing.
        """
        doc = get_doc()
        doc.setup_standard_layers()
        return "All AIA-standard layers created"

    @mcp.tool()
    def add_custom_layer(
        name: Annotated[str, Field(description="Layer name")],
        color: Annotated[int, Field(description="ACI colour index (1-255)")] = 7,
        linetype: Annotated[str, Field(description="Linetype name")] = "Continuous",
    ) -> str:
        """Add a custom layer to the active drawing."""
        doc = get_doc()
        doc.add_layer(name=name, color=color, linetype=linetype)
        return f"Layer '{name}' created (color={color}, linetype={linetype})"
