"""
North orientation detector.

Determines the rotation (degrees) of the drawing's Y-axis relative to true north.
  0°  = drawing up (+Y) is north  (most common)
  90° = drawing right (+X) is north (rotated plan)

Strategy:
  1. Block insertion named NORTH*, COMPASS, ARROW → read its rotation attribute
  2. TEXT / MTEXT entity whose text is "N" or "NORTH" → read rotation
  3. Assume 0° (north = drawing up) as fallback and document the assumption
"""

from __future__ import annotations

import re

from ezdxf.document import Drawing

# Block names that typically represent north arrows in engineering DWGs
_NORTH_BLOCKS: frozenset[str] = frozenset({
    "NORTH", "NORTH_ARROW", "NORTHARROW", "NORTH ARROW",
    "COMPASS", "TRUE NORTH", "TRUE_NORTH",
    "N_ARROW", "NARROW",
    "ORIENTATION", "ORIENT",
    "ARROW",
})

_NORTH_TEXT_RE = re.compile(r"^N(ORTH)?$", re.IGNORECASE)


def detect_north(doc: Drawing) -> tuple[float, list[str]]:
    """
    Returns:
        angle_deg : rotation angle in degrees (0 = north is drawing up)
        notes     : human-readable detection log
    """
    msp = doc.modelspace()
    notes: list[str] = []

    # ------------------------------------------------------------------
    # Strategy 1: Block insertion
    # ------------------------------------------------------------------
    for entity in msp:
        if entity.dxftype() != "INSERT":
            continue

        block_name: str = entity.dxf.name.upper().strip()

        matched = (
            block_name in _NORTH_BLOCKS
            or any(block_name.startswith(nb) for nb in _NORTH_BLOCKS)
        )
        if not matched:
            continue

        rotation: float = entity.dxf.rotation if entity.dxf.hasattr("rotation") else 0.0
        notes.append(
            f"North from block '{entity.dxf.name}' — rotation={rotation:.1f}°"
        )
        return rotation, notes

    notes.append("No north-arrow block found — checking TEXT entities")

    # ------------------------------------------------------------------
    # Strategy 2: Text entity
    # ------------------------------------------------------------------
    for entity in msp:
        if entity.dxftype() not in ("TEXT", "MTEXT"):
            continue

        try:
            text = (
                entity.plain_mtext()
                if entity.dxftype() == "MTEXT"
                else entity.dxf.text
            ).strip()
        except Exception:
            continue

        if _NORTH_TEXT_RE.match(text):
            rotation = entity.dxf.rotation if entity.dxf.hasattr("rotation") else 0.0
            notes.append(
                f"North from TEXT '{text}' — rotation={rotation:.1f}°"
            )
            return rotation, notes

    notes.append("No north indicator found — assuming north = drawing up (0°)")
    return 0.0, notes
