"""
3D isometric building outline generator.

Generates a BuildingOutline3D (wireframe vertex/edge list) from a BuildingDesign.
The wireframe extrudes the building footprint to each floor height, then adds the
roof geometry.

Also renders the wireframe to a DXF file using ezdxf 3D lines projected to 2D
using a standard isometric angle.

All coordinates are in metres.
"""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf
from ezdxf.layouts import Modelspace

from civilengineer.cad_layer.layer_manager import LayerManager
from civilengineer.schemas.design import BuildingDesign
from civilengineer.schemas.elevation import BuildingOutline3D, IsoEdge, IsoVertex

# Isometric projection angles
_ISO_ANGLE_X = math.radians(30)   # angle of X axis from horizontal
_ISO_ANGLE_Y = math.radians(150)  # angle of Y axis from horizontal


class Building3DGenerator:
    """
    Generates a 3D wireframe building outline from a BuildingDesign.

    The wireframe represents the outer massing of the building:
    - Ground level footprint
    - Each floor slab outline
    - Roof outline (with parapet)
    - Vertical corner lines

    It does NOT render individual rooms — only the outer envelope.
    """

    PARAPET_HEIGHT = 0.6  # metres above top floor slab

    def generate_outline(self, building: BuildingDesign) -> BuildingOutline3D:
        """
        Build the vertex/edge list for the 3D wireframe.

        Footprint is a rectangle: width (X) × depth (Y).
        Heights (Z) are stacked floor heights.
        """
        outline = BuildingOutline3D()

        bz = building.floor_plans[0].buildable_zone if building.floor_plans else None
        fp_x = bz.x if bz else 0.0
        fp_y = bz.y if bz else 0.0

        # Building footprint dimensions (use full plot width/depth for the outline)
        # In a real design we'd use the actual building envelope; for now use the
        # buildable zone width/depth.
        if bz:
            w = bz.width
            d = bz.depth
        else:
            w = building.plot_width
            d = building.plot_depth

        # Collect Z levels: 0 (ground) + top of each floor + parapet top
        z_levels: list[float] = [0.0]
        z = 0.0
        for fp in sorted(building.floor_plans, key=lambda f: f.floor):
            z += fp.floor_height
            z_levels.append(z)
        roof_top = z + self.PARAPET_HEIGHT
        z_levels.append(roof_top)

        # Footprint corners (XY) — origin at lower-left of buildable zone
        corners_xy = [
            (fp_x,     fp_y),
            (fp_x + w, fp_y),
            (fp_x + w, fp_y + d),
            (fp_x,     fp_y + d),
        ]

        # Build vertices: for each Z level, add all 4 corners
        # vertex_index[z_idx][corner_idx] → vertex list index
        vertex_index: list[list[int]] = []
        for z_val in z_levels:
            ring: list[int] = []
            for (cx, cy) in corners_xy:
                idx = len(outline.vertices)
                outline.vertices.append(IsoVertex(x=cx, y=cy, z=z_val))
                ring.append(idx)
            vertex_index.append(ring)

        # Vertical corner edges (connect same corner across all z levels)
        for z_idx in range(len(z_levels) - 1):
            for c_idx in range(4):
                is_roof = (z_idx == len(z_levels) - 2)
                outline.edges.append(IsoEdge(
                    start=vertex_index[z_idx][c_idx],
                    end=vertex_index[z_idx + 1][c_idx],
                    is_roof_edge=is_roof,
                ))

        # Horizontal ring edges at each Z level
        for z_idx, ring in enumerate(vertex_index):
            is_roof = (z_idx == len(z_levels) - 1)
            for c_idx in range(4):
                next_c = (c_idx + 1) % 4
                outline.edges.append(IsoEdge(
                    start=ring[c_idx],
                    end=ring[next_c],
                    is_roof_edge=is_roof,
                ))

        # Bounding box
        outline.bbox_x = w
        outline.bbox_y = d
        outline.bbox_z = roof_top

        return outline

    def render_dxf(self, outline: BuildingOutline3D, output_path: Path) -> None:
        """
        Write the 3D wireframe to a DXF file.

        Lines are drawn as true 3D LINE entities (ezdxf supports 3D coords).
        The file can be viewed in isometric projection in any CAD viewer.
        An isometric 2D projection is also drawn for reference.
        """
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 6  # metres
        doc.header["$MEASUREMENT"] = 1

        lm = LayerManager(doc)
        lm.setup_layers()

        msp = doc.modelspace()

        # Draw as true 3D lines
        self._draw_3d_lines(msp, outline)

        # Draw iso projection to the right (offset by bbox_x + 2m)
        x_offset = outline.bbox_x + 3.0
        self._draw_iso_projection(msp, outline, x_offset=x_offset, y_offset=0.0)

        # Labels
        msp.add_text(
            "3D WIREFRAME (SE ISOMETRIC)",
            dxfattribs={
                "layer": LayerManager.OUTLINE_3D,
                "height": 0.35,
                "insert": (x_offset + outline.bbox_x / 2, -0.6),
                "halign": 4,
                "valign": 0,
            },
        )

        doc.saveas(output_path)

    def _draw_3d_lines(self, msp: Modelspace, outline: BuildingOutline3D) -> None:
        """Draw each edge as a 3D LINE entity."""
        for edge in outline.edges:
            v0 = outline.vertices[edge.start]
            v1 = outline.vertices[edge.end]
            msp.add_line(
                start=(v0.x, v0.y, v0.z),
                end=(v1.x, v1.y, v1.z),
                dxfattribs={"layer": LayerManager.OUTLINE_3D},
            )

    def _draw_iso_projection(
        self,
        msp: Modelspace,
        outline: BuildingOutline3D,
        x_offset: float,
        y_offset: float,
    ) -> None:
        """
        Project the 3D wireframe to 2D using a standard SE isometric projection.

        Projection formulas:
            screen_x = (x - y) * cos(30°)
            screen_y = (x + y) * sin(30°) + z
        """
        def project(v: IsoVertex) -> tuple[float, float]:
            sx = (v.x - v.y) * math.cos(_ISO_ANGLE_X)
            sy = (v.x + v.y) * math.sin(_ISO_ANGLE_X) + v.z
            return sx + x_offset, sy + y_offset

        for edge in outline.edges:
            v0 = outline.vertices[edge.start]
            v1 = outline.vertices[edge.end]
            p0 = project(v0)
            p1 = project(v1)
            msp.add_line(
                start=(p0[0], p0[1]),
                end=(p1[0], p1[1]),
                dxfattribs={
                    "layer": LayerManager.OUTLINE_3D,
                    "lineweight": 50 if edge.is_roof_edge else 25,
                },
            )
