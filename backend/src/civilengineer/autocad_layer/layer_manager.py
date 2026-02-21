"""
AutoCAD COM layer setup — mirrors cad_layer.layer_manager but targets
the AutoCAD COM API (via AutoCADDocument) instead of ezdxf.

Usage
-----
    from civilengineer.autocad_layer.layer_manager import setup_com_layers
    setup_com_layers(doc)    # doc is an AutoCADDocument
"""

from __future__ import annotations

# Re-use the same layer definitions from the existing module
from civilengineer.cad_layer.layer_manager import LayerManager


def setup_com_layers(doc) -> None:
    """
    Create all AIA-standard layers in the given AutoCADDocument.

    `doc` is any object implementing `add_layer(name, color, linetype)`.
    Works with both ComDocument (real AutoCAD) and EzdxfDocument (fallback).
    """
    for ld in LayerManager.LAYER_DEFS:
        doc.add_layer(name=ld.name, color=ld.color, linetype=ld.linetype)
