"""
AIA-standard layer definitions for DXF output.

Layers follow the AIA CAD Layer Guidelines (second edition) naming convention.
Each layer has a fixed colour (ACI index) and linetype.

Usage:
    from civilengineer.cad_layer.layer_manager import LayerManager
    lm = LayerManager(doc)
    lm.setup_layers()
    entity.dxf.layer = LayerManager.WALL_EXT
"""

from __future__ import annotations

from dataclasses import dataclass

from ezdxf.document import Drawing


@dataclass(frozen=True)
class LayerDef:
    name: str
    color: int          # ACI colour index (1-255)
    linetype: str = "Continuous"
    lineweight: int = 25  # hundredths of mm (25 = 0.25 mm)
    description: str = ""


class LayerManager:
    """Registers and returns all project-standard layers."""

    # Plan layers
    WALL_EXT = "A-WALL-EXTR"
    WALL_INT_LOAD = "A-WALL-INT-LOAD"
    WALL_PART = "A-WALL-PART"
    DOOR = "A-DOOR"
    WINDOW = "A-WIND"
    ROOM_OUTLINE = "A-ROOM-OTLN"
    ROOM_LABEL = "A-ROOM-LABL"
    STAIR = "A-STAIR"
    COLUMN = "S-COLS"

    # Site / plot layers
    PLOT_BOUNDARY = "C-PLOT"
    SETBACK = "C-SETB"

    # Annotation layers
    DIMENSIONS = "A-ANNO-DIMS"
    TITLE_BLOCK = "A-ANNO-TITL"
    NORTH_ARROW = "A-ANNO-NRTH"

    # Elevation layers
    ELEV_OUTLINE = "A-ELEV-OUTL"
    ELEV_DETAIL = "A-ELEV-DETL"
    ELEV_ANNOTATION = "A-ELEV-ANNO"

    # 3D outline
    OUTLINE_3D = "A-3D-OUTL"

    # Ordered list of all layer definitions
    LAYER_DEFS: list[LayerDef] = [
        # ---- Plan ----
        LayerDef(WALL_EXT, color=7, lineweight=70,
                 description="External load-bearing walls"),
        LayerDef(WALL_INT_LOAD, color=7, lineweight=50,
                 description="Internal load-bearing walls"),
        LayerDef(WALL_PART, color=8, lineweight=25,
                 description="Partition walls (non-load-bearing)"),
        LayerDef(DOOR, color=30, lineweight=25,
                 description="Doors and swing arcs"),
        LayerDef(WINDOW, color=140, lineweight=25,
                 description="Window openings"),
        LayerDef(ROOM_OUTLINE, color=8, lineweight=18,
                 description="Room boundary reference polylines"),
        LayerDef(ROOM_LABEL, color=2, lineweight=18,
                 description="Room name and area text"),
        LayerDef(STAIR, color=6, lineweight=25,
                 description="Staircase symbols and outlines"),
        LayerDef(COLUMN, color=5, lineweight=50,
                 description="Structural columns (RC)"),

        # ---- Site ----
        LayerDef(PLOT_BOUNDARY, color=3, linetype="Continuous", lineweight=50,
                 description="Plot boundary (from input DWG)"),
        LayerDef(SETBACK, color=3, linetype="DASHED", lineweight=25,
                 description="Setback reference lines"),

        # ---- Annotation ----
        LayerDef(DIMENSIONS, color=8, lineweight=18,
                 description="Dimension strings"),
        LayerDef(TITLE_BLOCK, color=7, lineweight=35,
                 description="Title block border and text"),
        LayerDef(NORTH_ARROW, color=2, lineweight=25,
                 description="North arrow symbol"),

        # ---- Elevation ----
        LayerDef(ELEV_OUTLINE, color=7, lineweight=70,
                 description="Elevation wall outline"),
        LayerDef(ELEV_DETAIL, color=8, lineweight=25,
                 description="Elevation detail lines (floor bands, openings)"),
        LayerDef(ELEV_ANNOTATION, color=2, lineweight=18,
                 description="Elevation annotations (heights, labels)"),

        # ---- 3D ----
        LayerDef(OUTLINE_3D, color=7, lineweight=35,
                 description="3D building wireframe/outline"),
    ]

    # Map name → LayerDef for fast lookup
    _by_name: dict[str, LayerDef] = {ld.name: ld for ld in LAYER_DEFS}

    def __init__(self, doc: Drawing) -> None:
        self._doc = doc

    def setup_layers(self) -> None:
        """Create all project layers in the DXF document."""
        # Ensure DASHED linetype is loaded
        if "DASHED" not in self._doc.linetypes:
            self._doc.linetypes.new("DASHED", dxfattribs={"description": "Dashed"})

        layers = self._doc.layers
        for ld in self.LAYER_DEFS:
            if ld.name not in layers:
                layer = layers.new(ld.name)
            else:
                layer = layers.get(ld.name)
            layer.color = ld.color
            layer.linetype = ld.linetype
            layer.lineweight = ld.lineweight

    @classmethod
    def get_def(cls, name: str) -> LayerDef | None:
        return cls._by_name.get(name)
