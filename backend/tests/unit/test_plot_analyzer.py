"""
Unit tests for the plot analyser.

Uses ezdxf to construct minimal DXF documents in-memory (written to temp files
since ezdxf.readfile() requires a path).  No S3, Celery, or DB is needed.

Success criterion (from architecture plan):
    All test fixtures produce PlotInfo with extraction_confidence >= 0.8
    for the named-layer and mm-units cases.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import ezdxf
import pytest

from civilengineer.plot_analyzer.dwg_reader import analyze_dxf_file
from civilengineer.schemas.project import PlotFacing, PlotInfo


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _save_dxf(doc) -> Path:
    """Write an ezdxf document to a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    doc.saveas(path)
    return Path(path)


def _analyse(doc) -> PlotInfo:
    path = _save_dxf(doc)
    try:
        return analyze_dxf_file(path)
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 1. Rectangular plot on named layer (C-PLOT) in metres
# ---------------------------------------------------------------------------

class TestRectangularNamedLayer:
    """30 m × 20 m rectangle on layer C-PLOT, INSUNITS=6 (metres)."""

    def _doc(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 6
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (30, 0), (30, 20), (0, 20)],
            close=True,
            dxfattribs={"layer": "C-PLOT"},
        )
        return doc

    def test_area(self):
        info = _analyse(self._doc())
        assert abs(info.area_sqm - 600.0) < 1.0

    def test_dimensions(self):
        info = _analyse(self._doc())
        assert abs(info.width_m - 30.0) < 0.1
        assert abs(info.depth_m - 20.0) < 0.1

    def test_is_rectangular(self):
        assert _analyse(self._doc()).is_rectangular is True

    def test_polygon_vertex_count(self):
        assert len(_analyse(self._doc()).polygon) == 4

    def test_confidence_high(self):
        # Named-layer extraction should reach 0.95
        assert _analyse(self._doc()).extraction_confidence >= 0.9

    def test_scale_factor_metres(self):
        assert _analyse(self._doc()).scale_factor == 1.0


# ---------------------------------------------------------------------------
# 2. Irregular pentagon (no named layer) — largest-polygon strategy
# ---------------------------------------------------------------------------

class TestIrregularPolygonNoLayer:
    """L-shaped / pentagonal plot on the default layer '0'."""

    def _doc(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 6
        msp = doc.modelspace()
        # Irregular pentagon: vertices chosen so area ≈ 400 sqm
        msp.add_lwpolyline(
            [(0, 0), (25, 0), (30, 10), (15, 22), (0, 15)],
            close=True,
            dxfattribs={"layer": "0"},
        )
        return doc

    def test_vertex_count(self):
        assert len(_analyse(self._doc()).polygon) == 5

    def test_confidence(self):
        # Largest-polygon strategy: confidence 0.75
        assert _analyse(self._doc()).extraction_confidence >= 0.7

    def test_not_rectangular(self):
        assert _analyse(self._doc()).is_rectangular is False

    def test_area_positive(self):
        assert _analyse(self._doc()).area_sqm > 0.0

    def test_multiple_polylines_picks_largest(self):
        """Smaller decoration polylines must not override the plot boundary."""
        doc = self._doc()
        msp = doc.modelspace()
        # Add a tiny closed square (annotation — 1×1 m)
        msp.add_lwpolyline(
            [(0, 0), (1, 0), (1, 1), (0, 1)],
            close=True,
            dxfattribs={"layer": "0"},
        )
        info = _analyse(doc)
        # Should still pick the pentagon (larger area), not the 1×1 square
        assert len(info.polygon) == 5


# ---------------------------------------------------------------------------
# 3. North arrow block detection
# ---------------------------------------------------------------------------

class TestNorthArrowBlock:
    """Plot with a NORTH_ARROW block rotated 45°."""

    def _doc(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 6
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (20, 0), (20, 20), (0, 20)],
            close=True,
            dxfattribs={"layer": "C-PLOT"},
        )
        # Define block
        if "NORTH_ARROW" not in doc.blocks:
            blk = doc.blocks.new("NORTH_ARROW")
            blk.add_line((0, 0), (0, 1))
        # Insert at 45° rotation
        msp.add_blockref("NORTH_ARROW", (5, 5), dxfattribs={"rotation": 45.0})
        return doc

    def test_north_direction(self):
        info = _analyse(self._doc())
        assert abs(info.north_direction_deg - 45.0) < 1.0

    def test_facing_derived(self):
        """45° north → southwest facing (road at bottom-left)."""
        info = _analyse(self._doc())
        assert info.facing == PlotFacing.SOUTHWEST


class TestNorthTextEntity:
    """Plot with a TEXT entity 'N' at 90°."""

    def _doc(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 6
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (15, 0), (15, 15), (0, 15)],
            close=True,
            dxfattribs={"layer": "PLOT"},
        )
        msp.add_text(
            "N",
            dxfattribs={"insert": (20, 10), "height": 1.0, "rotation": 90.0},
        )
        return doc

    def test_north_from_text(self):
        info = _analyse(self._doc())
        assert abs(info.north_direction_deg - 90.0) < 1.0


# ---------------------------------------------------------------------------
# 4. Millimetre units (INSUNITS=4) — scale conversion
# ---------------------------------------------------------------------------

class TestMillimetreUnits:
    """20 000 mm × 15 000 mm = 20 m × 15 m plot."""

    def _doc(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 4   # mm
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (20000, 0), (20000, 15000), (0, 15000)],
            close=True,
            dxfattribs={"layer": "C-PLOT"},
        )
        return doc

    def test_area_converted_to_sqm(self):
        info = _analyse(self._doc())
        # 20 m × 15 m = 300 sqm
        assert abs(info.area_sqm - 300.0) < 1.0

    def test_dimensions_in_metres(self):
        info = _analyse(self._doc())
        assert abs(info.width_m - 20.0) < 0.1
        assert abs(info.depth_m - 15.0) < 0.1

    def test_scale_factor(self):
        assert abs(_analyse(self._doc()).scale_factor - 0.001) < 1e-9

    def test_confidence(self):
        assert _analyse(self._doc()).extraction_confidence >= 0.9


# ---------------------------------------------------------------------------
# 5. Feet units (INSUNITS=2)
# ---------------------------------------------------------------------------

class TestFeetUnits:
    """100 ft × 66 ft ≈ 30.48 m × 20.117 m."""

    def _doc(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 2   # feet
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (100, 0), (100, 66), (0, 66)],
            close=True,
            dxfattribs={"layer": "BOUNDARY"},
        )
        return doc

    def test_area_in_sqm(self):
        info = _analyse(self._doc())
        expected = 100 * 0.3048 * 66 * 0.3048
        assert abs(info.area_sqm - expected) < 0.5

    def test_scale_factor(self):
        assert abs(_analyse(self._doc()).scale_factor - 0.3048) < 1e-9


# ---------------------------------------------------------------------------
# 6. Site feature detection
# ---------------------------------------------------------------------------

class TestSiteFeatures:
    """Plot with a TREE block insertion and road text."""

    def _doc(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 6
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (20, 0), (20, 20), (0, 20)],
            close=True,
            dxfattribs={"layer": "C-PLOT"},
        )
        # Tree block
        if "TREE" not in doc.blocks:
            blk = doc.blocks.new("TREE")
            blk.add_circle((0, 0), 0.5)
        msp.add_blockref("TREE", (5, 5))
        # Road text
        msp.add_text("Road", dxfattribs={"insert": (10, -2), "height": 1.0})
        return doc

    def test_tree_detected(self):
        assert "tree" in _analyse(self._doc()).existing_features

    def test_road_detected(self):
        assert "road" in _analyse(self._doc()).existing_features

    def test_no_false_features(self):
        """A plain plot with no blocks/text should have no features."""
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 6
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            close=True,
            dxfattribs={"layer": "C-PLOT"},
        )
        assert _analyse(doc).existing_features == []


# ---------------------------------------------------------------------------
# 7. Default north facing
# ---------------------------------------------------------------------------

class TestDefaultFacing:
    """No north arrow → 0° assumed → SOUTH facing (road at bottom)."""

    def _doc(self):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 6
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            close=True,
            dxfattribs={"layer": "C-PLOT"},
        )
        return doc

    def test_facing_south_by_default(self):
        assert _analyse(self._doc()).facing == PlotFacing.SOUTH

    def test_north_zero(self):
        assert _analyse(self._doc()).north_direction_deg == 0.0


# ---------------------------------------------------------------------------
# 8. Empty DXF (no geometry) — graceful degradation
# ---------------------------------------------------------------------------

class TestEmptyDrawing:
    def _doc(self):
        return ezdxf.new("R2010")

    def test_zero_confidence(self):
        assert _analyse(self._doc()).extraction_confidence == 0.0

    def test_empty_polygon(self):
        assert _analyse(self._doc()).polygon == []

    def test_zero_area(self):
        assert _analyse(self._doc()).area_sqm == 0.0
