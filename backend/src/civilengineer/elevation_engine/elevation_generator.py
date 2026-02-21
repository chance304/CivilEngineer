"""
Elevation view generator.

Derives ElevationView objects (front, rear, left, right) from a BuildingDesign.
Each elevation shows:
  - Wall outline (full building width × total height)
  - Floor band lines (horizontal lines at each floor level)
  - Window and door openings at correct positions
  - Parapet (for flat roofs)
  - Floor height annotations

Then renders each ElevationView to a DXF file.

All coordinates are in metres.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.layouts import Modelspace

from civilengineer.cad_layer.layer_manager import LayerManager
from civilengineer.schemas.design import (
    BuildingDesign,
    FloorPlan,
    WallFace,
)
from civilengineer.schemas.elevation import (
    ElevationFace,
    ElevationSet,
    ElevationView,
    FloorBand,
    OpeningType,
    RoofType,
    WallOpening,
)

# DXF INSUNITS metres
_INSUNITS_METRES = 6


class ElevationGenerator:
    """Generates ElevationSet from a BuildingDesign and writes DXF files."""

    DEFAULT_PARAPET_HEIGHT = 0.6  # metres above top slab

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_elevation_set(self, building: BuildingDesign) -> ElevationSet:
        """
        Derive all four elevation views from the building design.

        The north-facing facade is labelled FRONT, and the others follow
        the compass direction of each face.
        """
        elevation_set = ElevationSet(design_id=building.design_id)

        face_map = {
            ElevationFace.FRONT: (WallFace.NORTH, "FRONT (NORTH)",  building.plot_width),
            ElevationFace.REAR:  (WallFace.SOUTH, "REAR (SOUTH)",   building.plot_width),
            ElevationFace.LEFT:  (WallFace.WEST,  "LEFT (WEST)",    building.plot_depth),
            ElevationFace.RIGHT: (WallFace.EAST,  "RIGHT (EAST)",   building.plot_depth),
        }

        total_height = self._total_height(building)

        for elev_face, (wall_face, label, face_width) in face_map.items():
            view = self._build_elevation_view(
                building, elev_face, wall_face, label, face_width, total_height
            )
            if elev_face == ElevationFace.FRONT:
                elevation_set.front = view
            elif elev_face == ElevationFace.REAR:
                elevation_set.rear = view
            elif elev_face == ElevationFace.LEFT:
                elevation_set.left = view
            elif elev_face == ElevationFace.RIGHT:
                elevation_set.right = view

        return elevation_set

    def render_elevation_dxf(
        self,
        view: ElevationView,
        output_path: Path,
        building: BuildingDesign | None = None,
    ) -> None:
        """Write a single ElevationView to a DXF file."""
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = _INSUNITS_METRES
        doc.header["$MEASUREMENT"] = 1

        lm = LayerManager(doc)
        lm.setup_layers()

        msp = doc.modelspace()
        self._draw_elevation(msp, view, building)

        doc.saveas(output_path)

    # ------------------------------------------------------------------
    # Elevation view construction
    # ------------------------------------------------------------------

    def _total_height(self, building: BuildingDesign) -> float:
        """Total height = sum of all floor heights + parapet."""
        total = sum(fp.floor_height for fp in building.floor_plans)
        return total + self.DEFAULT_PARAPET_HEIGHT

    def _build_elevation_view(
        self,
        building: BuildingDesign,
        elev_face: ElevationFace,
        wall_face: WallFace,
        north_label: str,
        face_width: float,
        total_height: float,
    ) -> ElevationView:
        view = ElevationView(
            face=elev_face,
            face_width=face_width,
            total_height=total_height,
            north_label=north_label,
            roof_type=RoofType.FLAT,
            parapet_height=self.DEFAULT_PARAPET_HEIGHT,
        )

        # Floor bands
        z = 0.0
        for fp in sorted(building.floor_plans, key=lambda f: f.floor):
            view.floor_bands.append(FloorBand(
                floor=fp.floor,
                bottom_z=z,
                top_z=z + fp.floor_height,
            ))
            # Extract openings on this face from all rooms on this floor
            self._extract_openings(view, fp, wall_face, z, face_width)
            z += fp.floor_height

        return view

    def _extract_openings(
        self,
        view: ElevationView,
        floor_plan: FloorPlan,
        wall_face: WallFace,
        floor_bottom_z: float,
        face_width: float,
    ) -> None:
        """
        Find windows and doors on `wall_face` for every room on this floor
        and add them as WallOpening objects to the view.

        Position along the face is computed from the room's position:
        - For NORTH/SOUTH faces: room.bounds.x + window.position_along_wall
        - For WEST/EAST faces:   room.bounds.y + window.position_along_wall
        """
        for room in floor_plan.rooms:
            b = room.bounds

            for window in room.windows:
                if window.wall_face != wall_face:
                    continue
                if wall_face in (WallFace.NORTH, WallFace.SOUTH):
                    pos_x = b.x + window.position_along_wall
                else:
                    pos_x = b.y + window.position_along_wall

                # For REAR and RIGHT faces, mirror horizontally
                if wall_face in (WallFace.SOUTH, WallFace.EAST):
                    pos_x = face_width - pos_x - window.width

                view.openings.append(WallOpening(
                    opening_type=OpeningType.WINDOW,
                    floor=floor_plan.floor,
                    position_x=max(0.0, pos_x),
                    sill_height=window.sill_height,
                    width=window.width,
                    height=window.height,
                ))

            for door in room.doors:
                if door.wall_face != wall_face:
                    continue
                if wall_face in (WallFace.NORTH, WallFace.SOUTH):
                    pos_x = b.x + door.position_along_wall
                else:
                    pos_x = b.y + door.position_along_wall

                if wall_face in (WallFace.SOUTH, WallFace.EAST):
                    pos_x = face_width - pos_x - door.width

                view.openings.append(WallOpening(
                    opening_type=OpeningType.DOOR,
                    floor=floor_plan.floor,
                    position_x=max(0.0, pos_x),
                    sill_height=0.0,
                    width=door.width,
                    height=2.1,  # standard door height
                ))

    # ------------------------------------------------------------------
    # DXF drawing
    # ------------------------------------------------------------------

    def _draw_elevation(
        self,
        msp: Modelspace,
        view: ElevationView,
        building: BuildingDesign | None,
    ) -> None:
        self._draw_wall_outline(msp, view)
        self._draw_floor_bands(msp, view)
        self._draw_openings(msp, view)
        self._draw_parapet(msp, view)
        self._draw_height_annotations(msp, view)
        self._draw_face_label(msp, view)

    def _draw_wall_outline(self, msp: Modelspace, view: ElevationView) -> None:
        """Outer perimeter of the elevation face."""
        wall_top = view.total_height - view.parapet_height
        pts = [
            (0.0, 0.0),
            (view.face_width, 0.0),
            (view.face_width, wall_top),
            (0.0, wall_top),
            (0.0, 0.0),
        ]
        msp.add_lwpolyline(pts, dxfattribs={"layer": LayerManager.ELEV_OUTLINE, "lineweight": 70})

    def _draw_floor_bands(self, msp: Modelspace, view: ElevationView) -> None:
        """Horizontal lines at each floor level."""
        for band in view.floor_bands:
            # Floor line (bottom of floor slab)
            if band.bottom_z > 0.0:
                msp.add_line(
                    (0.0, band.bottom_z),
                    (view.face_width, band.bottom_z),
                    dxfattribs={"layer": LayerManager.ELEV_DETAIL},
                )
            # Top of floor (ceiling / underside of slab above)
            msp.add_line(
                (0.0, band.top_z),
                (view.face_width, band.top_z),
                dxfattribs={"layer": LayerManager.ELEV_DETAIL},
            )

    def _draw_openings(self, msp: Modelspace, view: ElevationView) -> None:
        """Draw window and door openings as rectangles with cross-lines."""
        # Build floor-to-z lookup
        floor_z = {band.floor: band.bottom_z for band in view.floor_bands}

        for op in view.openings:
            base_z = floor_z.get(op.floor, 0.0)
            x0 = op.position_x
            x1 = op.position_x + op.width
            y0 = base_z + op.sill_height
            y1 = y0 + op.height

            # Opening rectangle (cut-out)
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            msp.add_lwpolyline(pts, dxfattribs={"layer": LayerManager.ELEV_DETAIL})

            # Cross lines (X) inside opening to indicate void
            msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": LayerManager.ELEV_DETAIL})
            msp.add_line((x1, y0), (x0, y1), dxfattribs={"layer": LayerManager.ELEV_DETAIL})

    def _draw_parapet(self, msp: Modelspace, view: ElevationView) -> None:
        """Draw flat roof parapet above wall outline."""
        wall_top = view.total_height - view.parapet_height
        roof_top = view.total_height
        # Parapet left
        msp.add_line(
            (0.0, wall_top),
            (0.0, roof_top),
            dxfattribs={"layer": LayerManager.ELEV_OUTLINE},
        )
        # Parapet right
        msp.add_line(
            (view.face_width, wall_top),
            (view.face_width, roof_top),
            dxfattribs={"layer": LayerManager.ELEV_OUTLINE},
        )
        # Parapet cap
        msp.add_line(
            (0.0, roof_top),
            (view.face_width, roof_top),
            dxfattribs={"layer": LayerManager.ELEV_OUTLINE, "lineweight": 70},
        )

    def _draw_height_annotations(self, msp: Modelspace, view: ElevationView) -> None:
        """Vertical dimension annotations for each floor height."""
        ann_x = view.face_width + 0.8
        text_h = 0.20

        for band in view.floor_bands:
            # Leader line + text
            msp.add_line(
                (view.face_width, band.bottom_z),
                (ann_x, band.bottom_z),
                dxfattribs={"layer": LayerManager.ELEV_ANNOTATION},
            )
            msp.add_line(
                (view.face_width, band.top_z),
                (ann_x, band.top_z),
                dxfattribs={"layer": LayerManager.ELEV_ANNOTATION},
            )
            # Height label
            mid_z = (band.bottom_z + band.top_z) / 2
            floor_h = band.top_z - band.bottom_z
            msp.add_text(
                f"F{band.floor}: {floor_h:.2f}m",
                dxfattribs={
                    "layer": LayerManager.ELEV_ANNOTATION,
                    "height": text_h,
                    "insert": (ann_x + 0.1, mid_z),
                    "halign": 0,
                    "valign": 0,
                },
            )
            # RL (Reduced Level) at bottom
            msp.add_text(
                f"RL +{band.bottom_z:.2f}",
                dxfattribs={
                    "layer": LayerManager.ELEV_ANNOTATION,
                    "height": text_h * 0.85,
                    "insert": (ann_x + 0.1, band.bottom_z + 0.05),
                    "halign": 0,
                    "valign": 0,
                },
            )

        # Total height annotation
        msp.add_text(
            f"Total H: {view.total_height:.2f}m",
            dxfattribs={
                "layer": LayerManager.ELEV_ANNOTATION,
                "height": text_h,
                "insert": (ann_x + 0.1, view.total_height + 0.2),
                "halign": 0,
                "valign": 0,
            },
        )

    def _draw_face_label(self, msp: Modelspace, view: ElevationView) -> None:
        """Title label below the elevation drawing."""
        msp.add_text(
            view.north_label,
            dxfattribs={
                "layer": LayerManager.ELEV_ANNOTATION,
                "height": 0.35,
                "insert": (view.face_width / 2, -0.6),
                "halign": 4,
                "valign": 0,
            },
        )
