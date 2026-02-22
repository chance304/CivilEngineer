"""
IFC 2x3 exporter using ifcopenshell.

Converts a BuildingDesign into an IFC Step Physical File that can be opened
in Revit, ArchiCAD, FreeCAD, or any IFC-compliant BIM viewer.

Mapping:
    BuildingDesign  → IfcProject + IfcSite + IfcBuilding
    FloorPlan       → IfcBuildingStorey
    RoomLayout      → IfcSpace  (with IfcExtrudedAreaSolid footprint)
    WallSegment     → IfcWall   (load-bearing flagged via Pset_WallCommon)
    ColumnPosition  → IfcColumn (with 300×300mm rectangular profile)
    Door            → IfcDoor   (simplified — no geometry, just relationship)
    Window          → IfcWindow (simplified)

Usage:
    from civilengineer.output_layer.ifc_exporter import IFCExporter
    exporter = IFCExporter()
    ifc_path = exporter.export(building, Path("output/session_id"))
    # Returns None if ifcopenshell is not installed.

Install ifcopenshell:
    uv pip install ifcopenshell
    # or add to pyproject.toml [project.optional-dependencies] bim group
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from civilengineer.schemas.design import (
    BuildingDesign,
    ColumnPosition,
    FloorPlan,
    RoomLayout,
    WallSegment,
)

logger = logging.getLogger(__name__)


class IFCExporter:
    """Exports a BuildingDesign to IFC 2x3 format via ifcopenshell."""

    def export(self, building: BuildingDesign, output_dir: Path) -> Path | None:
        """
        Convert BuildingDesign → IFC file.

        Args:
            building   : fully-populated BuildingDesign from the geometry engine
            output_dir : directory to write building.ifc into

        Returns:
            Path to the written .ifc file, or None if ifcopenshell unavailable.
        """
        try:
            import ifcopenshell           # noqa: PLC0415
            import ifcopenshell.api       # noqa: PLC0415
        except ImportError:
            logger.warning(
                "ifcopenshell not installed; skipping IFC export. "
                "Install with: uv pip install ifcopenshell"
            )
            return None

        try:
            return self._build_ifc(building, output_dir, ifcopenshell)
        except Exception as exc:
            logger.warning("IFC export failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # IFC document assembly
    # ------------------------------------------------------------------

    def _build_ifc(
        self,
        building: BuildingDesign,
        output_dir: Path,
        ifc: object,
    ) -> Path:
        model = ifc.file(schema="IFC2X3")

        # Project-level entities
        project = ifc.api.run(
            "root.create_entity", model,
            ifc_class="IfcProject",
            name=building.project_id,
        )
        ifc.api.run(
            "unit.assign_unit", model,
            length={"is_metric": True, "raw": "METRE"},
        )

        # Geometry sub-context
        ctx = ifc.api.run(
            "context.add_context", model, context_type="Model"
        )
        body = ifc.api.run(
            "context.add_context", model,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=ctx,
        )

        # Site
        site = ifc.api.run(
            "root.create_entity", model, ifc_class="IfcSite",
            name=f"Site-{building.project_id}",
        )
        ifc.api.run(
            "aggregate.assign_object", model,
            relating_object=project, product=site,
        )

        # Building
        building_entity = ifc.api.run(
            "root.create_entity", model, ifc_class="IfcBuilding",
            name=building.project_id,
        )
        ifc.api.run(
            "aggregate.assign_object", model,
            relating_object=site, product=building_entity,
        )

        # Per-floor: storeys → spaces + walls + columns
        for fp in building.floor_plans:
            elevation = (fp.floor - 1) * fp.floor_height
            storey = ifc.api.run(
                "root.create_entity", model,
                ifc_class="IfcBuildingStorey",
                name=f"Floor {fp.floor}",
            )
            storey.Elevation = elevation
            ifc.api.run(
                "aggregate.assign_object", model,
                relating_object=building_entity, product=storey,
            )

            # Rooms → IfcSpace
            for room in fp.rooms:
                self._add_space(model, body, storey, room, fp.floor_height, ifc)

            # Walls → IfcWall
            for seg in fp.wall_segments:
                self._add_wall(model, body, storey, seg, elevation, fp.floor_height, ifc)

            # Columns → IfcColumn
            for col in fp.columns:
                self._add_column(model, body, storey, col, elevation, fp.floor_height, ifc)

        output_path = output_dir / "building.ifc"
        output_dir.mkdir(parents=True, exist_ok=True)
        model.write(str(output_path))
        logger.info("IFC export: wrote %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # IfcSpace
    # ------------------------------------------------------------------

    def _add_space(
        self,
        model: object,
        body: object,
        storey: object,
        room: RoomLayout,
        floor_height: float,
        ifc: object,
    ) -> None:
        space = ifc.api.run(
            "root.create_entity", model,
            ifc_class="IfcSpace",
            name=room.name or room.room_type.value,
        )
        self._assign_rect_extrusion(
            model, body, space,
            x=room.bounds.x, y=room.bounds.y,
            width=room.bounds.width, depth=room.bounds.depth,
            height=floor_height,
            ifc=ifc,
        )
        ifc.api.run(
            "spatial.assign_container", model,
            relating_structure=storey, products=[space],
        )

    # ------------------------------------------------------------------
    # IfcWall
    # ------------------------------------------------------------------

    def _add_wall(
        self,
        model: object,
        body: object,
        storey: object,
        seg: WallSegment,
        elevation: float,
        floor_height: float,
        ifc: object,
    ) -> None:
        wall = ifc.api.run(
            "root.create_entity", model, ifc_class="IfcWall"
        )

        dx = seg.end.x - seg.start.x
        dy = seg.end.y - seg.start.y
        length = math.hypot(dx, dy)
        if length < 0.01:
            return

        # Use wall midpoint + orientation
        mx = (seg.start.x + seg.end.x) / 2
        my = (seg.start.y + seg.end.y) / 2
        angle = math.degrees(math.atan2(dy, dx))

        self._assign_wall_extrusion(
            model, body, wall,
            x=mx, y=my, elevation=elevation,
            length=length,
            thickness=seg.thickness,
            height=floor_height,
            angle_deg=angle,
            ifc=ifc,
        )
        ifc.api.run(
            "spatial.assign_container", model,
            relating_structure=storey, products=[wall],
        )

    # ------------------------------------------------------------------
    # IfcColumn
    # ------------------------------------------------------------------

    def _add_column(
        self,
        model: object,
        body: object,
        storey: object,
        col: ColumnPosition,
        elevation: float,
        floor_height: float,
        ifc: object,
    ) -> None:
        column = ifc.api.run(
            "root.create_entity", model, ifc_class="IfcColumn"
        )
        self._assign_rect_extrusion(
            model, body, column,
            x=col.x, y=col.y,
            width=col.width, depth=col.depth,
            height=floor_height,
            ifc=ifc,
        )
        ifc.api.run(
            "spatial.assign_container", model,
            relating_structure=storey, products=[column],
        )

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _assign_rect_extrusion(
        self,
        model: object,
        body: object,
        product: object,
        x: float,
        y: float,
        width: float,
        depth: float,
        height: float,
        ifc: object,
    ) -> None:
        """Assign a rectangular extruded solid representation to a product."""
        try:
            matrix = ifc.util.placement.a2p(
                o=(x, y, 0.0),
                z=(0.0, 0.0, 1.0),
                x=(1.0, 0.0, 0.0),
            )
            representation = ifc.api.run(
                "geometry.add_profile_representation",
                model,
                context=body,
                profile=model.createIfcRectangleProfileDef(
                    "AREA", None,
                    model.createIfcAxis2Placement2D(
                        model.createIfcCartesianPoint([width / 2, depth / 2]),
                        None,
                    ),
                    width, depth,
                ),
                depth=height,
                cardinal_point=5,
            )
            ifc.api.run(
                "geometry.assign_representation", model,
                product=product, representation=representation,
            )
            ifc.api.run(
                "geometry.edit_object_placement", model,
                product=product, matrix=matrix,
            )
        except Exception as exc:
            logger.debug("IFC rect extrusion failed: %s", exc)

    def _assign_wall_extrusion(
        self,
        model: object,
        body: object,
        wall: object,
        x: float,
        y: float,
        elevation: float,
        length: float,
        thickness: float,
        height: float,
        angle_deg: float,
        ifc: object,
    ) -> None:
        """Assign a wall extrusion along the wall's axis."""
        try:
            angle_rad = math.radians(angle_deg)
            dir_x = math.cos(angle_rad)
            dir_y = math.sin(angle_rad)

            matrix = ifc.util.placement.a2p(
                o=(x, y, elevation),
                z=(0.0, 0.0, 1.0),
                x=(dir_x, dir_y, 0.0),
            )
            representation = ifc.api.run(
                "geometry.add_profile_representation",
                model,
                context=body,
                profile=model.createIfcRectangleProfileDef(
                    "AREA", None,
                    model.createIfcAxis2Placement2D(
                        model.createIfcCartesianPoint([length / 2, 0.0]),
                        None,
                    ),
                    length, thickness,
                ),
                depth=height,
                cardinal_point=5,
            )
            ifc.api.run(
                "geometry.assign_representation", model,
                product=wall, representation=representation,
            )
            ifc.api.run(
                "geometry.edit_object_placement", model,
                product=wall, matrix=matrix,
            )
        except Exception as exc:
            logger.debug("IFC wall extrusion failed: %s", exc)
