"""
CivilEngineer MCP Tool Server.

Exposes AutoCAD drawing capabilities as Model Context Protocol (MCP) tools
via a FastMCP stdio server.  The agent (LangGraph graph) can call these
tools to drive floor-plan drawing without knowing whether AutoCAD or the
ezdxf fallback is in use.

Usage (stdio transport — default for Claude Desktop + local agents)
-------------------------------------------------------------------
    # Start the server (attached to a running agent)
    python -m civilengineer.mcp_server.server

    # Or programmatically (for testing / embedding)
    from civilengineer.mcp_server.server import build_server, get_active_doc
    server = build_server()

Tool groups registered
----------------------
    Drawing:     draw_line, draw_polyline, draw_rectangle, draw_hatch
    Elements:    place_door, place_window, add_room_label, place_staircase
    Annotation:  add_linear_dimension, add_text, add_title_block, add_north_arrow
    File:        save_drawing, setup_layers, add_custom_layer
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from civilengineer.autocad_layer.com_driver import (
    AutoCADDocument,
    AutoCADDriver,
    EzdxfDocument,
)
from civilengineer.mcp_server.tools.annotation_tools import register_annotation_tools
from civilengineer.mcp_server.tools.drawing_tools import register_drawing_tools
from civilengineer.mcp_server.tools.element_tools import register_element_tools
from civilengineer.mcp_server.tools.file_tools import register_file_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active document state
# ---------------------------------------------------------------------------

_active_doc: AutoCADDocument | None = None
_driver: AutoCADDriver | None = None


def get_active_doc() -> AutoCADDocument:
    """
    Return the currently active AutoCADDocument.

    If no document is open, creates a new EzdxfDocument as fallback.
    """
    global _active_doc
    if _active_doc is None:
        logger.warning("No active document — creating new EzdxfDocument.")
        _active_doc = EzdxfDocument()
    return _active_doc


def set_active_doc(doc: AutoCADDocument) -> None:
    """Set the active document (used by the agent before calling tools)."""
    global _active_doc
    _active_doc = doc


def open_document(path: str | None = None) -> AutoCADDocument:
    """
    Open or create a drawing and make it the active document.

    Connects to AutoCAD if available; falls back to ezdxf otherwise.
    """
    global _active_doc, _driver
    _driver = AutoCADDriver(fallback_to_dxf=True)
    _driver.connect()
    _active_doc = _driver.open_or_new(path)
    return _active_doc


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def build_server(name: str = "civilengineer") -> FastMCP:
    """
    Build and return the FastMCP server with all tool groups registered.

    The returned server is *not* started; call server.run() for stdio.
    """
    mcp = FastMCP(
        name=name,
        instructions=(
            "CivilEngineer drawing tools. Call open_document before drawing, "
            "then use draw_* and place_* tools, finish with save_drawing."
        ),
    )

    # Register additional document management tools
    @mcp.tool()
    def open_document_tool(
        path: str = "",
    ) -> str:
        """Open or create a drawing. Call this before any drawing tools."""
        doc = open_document(path or None)
        doc.setup_standard_layers()
        return "Document opened and AIA layers created."

    # Register all tool groups
    register_drawing_tools(mcp, get_active_doc)
    register_element_tools(mcp, get_active_doc)
    register_annotation_tools(mcp, get_active_doc)
    register_file_tools(mcp, get_active_doc)

    return mcp


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the MCP server with stdio transport."""
    import sys  # noqa: PLC0415

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    )
    server = build_server()
    logger.info("CivilEngineer MCP server starting (stdio)…")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
