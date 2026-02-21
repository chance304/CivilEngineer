"""
Plot boundary extractor.

Extracts the plot boundary polygon from a DXF model space.

Strategy (in order of confidence):
  1. Named layer — closed LWPOLYLINE/POLYLINE on a known plot layer
  2. Largest closed polygon — biggest closed polyline in the drawing
  3. HATCH entity — boundary path of the first suitable hatch
  4. Fallback — returns empty list with confidence 0.0
"""

from __future__ import annotations

import math

from ezdxf.document import Drawing

from civilengineer.schemas.design import Point2D

# Layer names that engineers commonly use for the plot boundary
_PLOT_LAYERS: frozenset[str] = frozenset({
    "C-PLOT", "PLOT", "PLOT BOUNDARY", "PLOT-BOUNDARY",
    "BOUNDARY", "SITE", "SITE BOUNDARY", "SITE-BOUNDARY",
    "PLOT AREA", "PROPERTY LINE", "PROPERTY", "LAND",
    "SETBACK",   # sometimes the outer setback line is the only closed polyline
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lwpolyline_vertices(entity) -> list[tuple[float, float]]:
    return [(v[0], v[1]) for v in entity.get_points()]


def _polyline_vertices(entity) -> list[tuple[float, float]]:
    return [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]


def _shoelace_area(pts: list[tuple[float, float]]) -> float:
    """Signed shoelace area — returns absolute value."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
               for i in range(n))
    return abs(area) / 2.0


def _entity_is_closed(entity, pts: list[tuple[float, float]]) -> bool:
    """Return True if the entity is a closed polygon."""
    # Explicit closed flag on LWPOLYLINE
    if hasattr(entity, "is_closed") and entity.is_closed:
        return True
    # Old-style POLYLINE closed flag (bit 1)
    if hasattr(entity, "dxf") and entity.dxf.hasattr("flags") and (entity.dxf.flags & 1):
        return True
    # First vertex == last vertex (within tolerance)
    if len(pts) >= 2:
        dx = pts[-1][0] - pts[0][0]
        dy = pts[-1][1] - pts[0][1]
        if math.hypot(dx, dy) < 1e-6:
            return True
    return False


def _strip_closing_vertex(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remove duplicate last vertex if it matches first."""
    if len(pts) > 1 and math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]) < 1e-6:
        return pts[:-1]
    return pts


def _all_closed_polylines(msp) -> list[tuple[list[tuple[float, float]], object]]:
    """Collect all closed polylines as (vertices, entity) pairs."""
    results = []
    for entity in msp:
        dxftype = entity.dxftype()
        pts: list[tuple[float, float]] | None = None

        if dxftype == "LWPOLYLINE":
            pts = _lwpolyline_vertices(entity)
        elif dxftype == "POLYLINE":
            try:
                if entity.is_2d_polyline:
                    pts = _polyline_vertices(entity)
            except Exception:
                pass

        if pts and len(pts) >= 3 and _entity_is_closed(entity, pts):
            results.append((_strip_closing_vertex(pts), entity))

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_boundary(
    doc: Drawing,
) -> tuple[list[Point2D], float, list[str]]:
    """
    Extract the plot boundary from the DXF document.

    Returns:
        polygon     : closed polygon vertices (first ≠ last), in DXF units
        confidence  : 0.0–1.0
        notes       : human-readable extraction log
    """
    msp = doc.modelspace()
    notes: list[str] = []

    # ------------------------------------------------------------------
    # Strategy 1: Named plot layer
    # ------------------------------------------------------------------
    for entity in msp:
        dxftype = entity.dxftype()
        layer = entity.dxf.layer.upper().strip() if entity.dxf.hasattr("layer") else ""

        if layer not in _PLOT_LAYERS:
            continue

        pts: list[tuple[float, float]] | None = None

        if dxftype == "LWPOLYLINE":
            raw = _lwpolyline_vertices(entity)
            if len(raw) >= 3 and _entity_is_closed(entity, raw):
                pts = _strip_closing_vertex(raw)
        elif dxftype == "POLYLINE":
            try:
                if entity.is_2d_polyline:
                    raw = _polyline_vertices(entity)
                    if len(raw) >= 3 and _entity_is_closed(entity, raw):
                        pts = _strip_closing_vertex(raw)
            except Exception:
                pass

        if pts:
            notes.append(
                f"Boundary from named layer '{entity.dxf.layer}' — {len(pts)} vertices"
            )
            return [Point2D(x=p[0], y=p[1]) for p in pts], 0.95, notes

    notes.append("No named plot layer found — trying largest closed polygon")

    # ------------------------------------------------------------------
    # Strategy 2: Largest closed polygon
    # ------------------------------------------------------------------
    candidates = _all_closed_polylines(msp)
    if candidates:
        candidates.sort(key=lambda t: _shoelace_area(t[0]), reverse=True)
        best_pts, best_entity = candidates[0]
        layer = best_entity.dxf.layer if best_entity.dxf.hasattr("layer") else "0"
        notes.append(
            f"Boundary from largest polygon on layer '{layer}' — {len(best_pts)} vertices"
        )
        return [Point2D(x=p[0], y=p[1]) for p in best_pts], 0.75, notes

    notes.append("No closed polylines — trying HATCH entities")

    # ------------------------------------------------------------------
    # Strategy 3: HATCH boundary path
    # ------------------------------------------------------------------
    for entity in msp:
        if entity.dxftype() != "HATCH":
            continue
        try:
            for path in entity.paths:
                raw_pts: list[tuple[float, float]] = []
                if hasattr(path, "vertices"):
                    raw_pts = [(v[0], v[1]) for v in path.vertices]
                elif hasattr(path, "edges"):
                    for edge in path.edges:
                        if hasattr(edge, "start"):
                            raw_pts.append((edge.start.x, edge.start.y))
                if len(raw_pts) >= 3:
                    notes.append(
                        f"Boundary from HATCH entity — {len(raw_pts)} vertices"
                    )
                    return [Point2D(x=p[0], y=p[1]) for p in raw_pts], 0.55, notes
        except Exception as exc:
            notes.append(f"HATCH extraction error: {exc}")

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------
    notes.append("WARNING: no boundary found — empty result with confidence 0.0")
    return [], 0.0, notes
