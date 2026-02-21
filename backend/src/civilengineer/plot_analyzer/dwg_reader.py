"""
DWG/DXF reader — main entry point for plot analysis.

Accepts a file path or raw bytes and returns a fully-populated PlotInfo.
All spatial output values are in metres.

INSUNITS header value → metres conversion factor table:
  0  Unitless (inferred from polygon size)
  1  Inches   × 0.0254
  2  Feet     × 0.3048
  4  mm       × 0.001
  5  cm       × 0.01
  6  Metres   × 1.0
  8  Miles    × 1609.344
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import ezdxf

from civilengineer.plot_analyzer.boundary_extractor import extract_boundary
from civilengineer.plot_analyzer.orientation_detector import detect_north
from civilengineer.plot_analyzer.site_feature_extractor import extract_features
from civilengineer.schemas.design import Point2D
from civilengineer.schemas.project import PlotFacing, PlotInfo

# INSUNITS code → metres
_INSUNITS_TO_M: dict[int, float] = {
    0: 1.0,         # Unitless — will infer
    1: 0.0254,      # Inches
    2: 0.3048,      # Feet
    4: 0.001,       # Millimetres
    5: 0.01,        # Centimetres
    6: 1.0,         # Metres (native)
    8: 1609.344,    # Miles
    14: 1e-6,       # Microns
    15: 0.1,        # Decimetres
    16: 10.0,       # Dekametres
    17: 100.0,      # Hectometres
    18: 1000.0,     # Kilometres
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_scale_factor(doc: ezdxf.document.Drawing) -> tuple[float, list[str]]:
    notes: list[str] = []
    insunits: int = doc.header.get("$INSUNITS", 0)
    scale = _INSUNITS_TO_M.get(insunits, None)

    if scale is None:
        notes.append(f"Unknown INSUNITS={insunits} — defaulting to metres (×1.0)")
        return 1.0, notes

    unit_names = {1: "inches", 2: "feet", 4: "mm", 5: "cm", 6: "metres"}
    label = unit_names.get(insunits, str(insunits))

    if insunits == 0:
        notes.append("INSUNITS=0 (unitless) — will infer from polygon dimensions")
    else:
        notes.append(f"INSUNITS={insunits} ({label}) → scale={scale}")

    return scale, notes


def _infer_scale(pts: list[Point2D]) -> float:
    """
    If INSUNITS=0 (unitless), infer the unit from raw polygon dimensions.
    Civil DWGs in Nepal/India are typically 100–5000 sqm.
    """
    if len(pts) < 2:
        return 1.0
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    bbox_w = max(xs) - min(xs)
    bbox_h = max(ys) - min(ys)
    bbox_area = bbox_w * bbox_h

    if bbox_area > 500_000:     # likely millimetres
        return 0.001
    if bbox_area > 5_000:       # likely centimetres
        return 0.01
    return 1.0                  # assume metres


def _bounding_box(pts: list[Point2D]) -> tuple[float, float, float, float]:
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _polygon_area(pts: list[Point2D]) -> float:
    """Shoelace formula. Result is in the same units as pts.x / pts.y."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = sum(
        pts[i].x * pts[(i + 1) % n].y - pts[(i + 1) % n].x * pts[i].y
        for i in range(n)
    )
    return abs(area) / 2.0


def _is_rectangular(pts: list[Point2D], tolerance: float = 0.05) -> bool:
    """True when polygon area ≈ bounding-box area (within tolerance)."""
    if len(pts) < 3:
        return False
    min_x, min_y, max_x, max_y = _bounding_box(pts)
    bbox_area = (max_x - min_x) * (max_y - min_y)
    if bbox_area < 1e-9:
        return False
    poly_area = _polygon_area(pts)
    return abs(poly_area / bbox_area - 1.0) <= tolerance


def _derive_facing(north_deg: float) -> PlotFacing:
    """
    Heuristic: if north is at <angle> in the drawing, the road (bottom edge)
    typically faces the opposite direction.
    """
    angle = north_deg % 360
    if angle < 22.5 or angle >= 337.5:
        return PlotFacing.SOUTH       # north up → road south
    elif angle < 67.5:
        return PlotFacing.SOUTHWEST
    elif angle < 112.5:
        return PlotFacing.WEST
    elif angle < 157.5:
        return PlotFacing.NORTHWEST
    elif angle < 202.5:
        return PlotFacing.NORTH
    elif angle < 247.5:
        return PlotFacing.NORTHEAST
    elif angle < 292.5:
        return PlotFacing.EAST
    else:
        return PlotFacing.SOUTHEAST


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_dxf_bytes(data: bytes, storage_key: str = "") -> PlotInfo:
    """Parse a DXF file from raw bytes and return PlotInfo."""
    fd, tmp_path = tempfile.mkstemp(suffix=".dxf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return analyze_dxf_file(Path(tmp_path), storage_key=storage_key)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def analyze_dxf_file(
    path: str | Path,
    storage_key: str = "",
) -> PlotInfo:
    """Parse a DXF file from disk and return PlotInfo."""
    all_notes: list[str] = []

    doc = ezdxf.readfile(str(path))

    # --- Scale factor ---
    scale_factor, scale_notes = _get_scale_factor(doc)
    all_notes.extend(scale_notes)

    # --- Boundary ---
    polygon_raw, boundary_confidence, boundary_notes = extract_boundary(doc)
    all_notes.extend(boundary_notes)

    if not polygon_raw:
        return PlotInfo(
            dwg_storage_key=storage_key,
            polygon=[],
            area_sqm=0.0,
            width_m=0.0,
            depth_m=0.0,
            is_rectangular=False,
            north_direction_deg=0.0,
            facing=None,
            existing_features=[],
            scale_factor=scale_factor,
            extraction_confidence=0.0,
            extraction_notes=all_notes,
        )

    # --- Infer scale if unitless ---
    insunits: int = doc.header.get("$INSUNITS", 0)
    if insunits == 0:
        inferred = _infer_scale(polygon_raw)
        if inferred != 1.0:
            scale_factor = inferred
            all_notes.append(f"Inferred scale={scale_factor} from polygon dimensions")

    # --- Apply scale ---
    polygon = [Point2D(x=p.x * scale_factor, y=p.y * scale_factor) for p in polygon_raw]

    # --- Derived geometry ---
    area_sqm = _polygon_area(polygon)
    min_x, min_y, max_x, max_y = _bounding_box(polygon)
    width_m = max_x - min_x
    depth_m = max_y - min_y
    is_rect = _is_rectangular(polygon)

    all_notes.append(
        f"Plot: area={area_sqm:.1f} sqm, {width_m:.2f}×{depth_m:.2f} m, "
        f"rectangular={is_rect}"
    )

    # --- North orientation ---
    north_deg, north_notes = detect_north(doc)
    all_notes.extend(north_notes)
    facing = _derive_facing(north_deg)

    # --- Site features ---
    features, feature_notes = extract_features(doc)
    all_notes.extend(feature_notes)

    # --- Confidence sanity check ---
    confidence = boundary_confidence
    if area_sqm < 10.0:
        confidence = min(confidence, 0.4)
        all_notes.append(f"WARNING: very small area ({area_sqm:.2f} sqm) — check units")
    elif area_sqm > 100_000:
        confidence = min(confidence, 0.4)
        all_notes.append(f"WARNING: very large area ({area_sqm:.0f} sqm) — check units")

    return PlotInfo(
        dwg_storage_key=storage_key,
        polygon=polygon,
        area_sqm=round(area_sqm, 2),
        width_m=round(width_m, 3),
        depth_m=round(depth_m, 3),
        is_rectangular=is_rect,
        north_direction_deg=round(north_deg, 1),
        facing=facing,
        existing_features=features,
        scale_factor=scale_factor,
        extraction_confidence=round(confidence, 3),
        extraction_notes=all_notes,
    )
