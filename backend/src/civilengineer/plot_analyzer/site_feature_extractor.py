"""
Site feature extractor.

Detects trees, roads, existing structures, water bodies, parking areas, and
other site elements from block insertions, layer names, and text entities.

Returns a list of feature tags such as:
    ["tree", "road", "existing_structure", "water_body", "parking", "drain", "well"]
"""

from __future__ import annotations

from ezdxf.document import Drawing

# Partial block name matches (uppercase) → feature tag
_BLOCK_FEATURE_MAP: dict[str, str] = {
    "TREE": "tree",
    "PLANT": "tree",
    "SHRUB": "tree",
    "VEGETATION": "tree",
    "CAR": "parking",
    "VEHICLE": "parking",
    "PARKING": "parking",
    "MANHOLE": "drain",
    "DRAINAGE": "drain",
    "CULVERT": "drain",
    "LAMP": "streetlight",
    "LIGHT": "streetlight",
    "POLE": "streetlight",
}

# Layer name fragments (uppercase) → feature tag
_LAYER_FEATURE_MAP: dict[str, str] = {
    "ROAD": "road",
    "STREET": "road",
    "C-ROAD": "road",
    "C-TOPO": "road",
    "WATER": "water_body",
    "POND": "water_body",
    "RIVER": "water_body",
    "CANAL": "water_body",
    "DRAIN": "drain",
    "NALA": "drain",
    "SEWER": "drain",
    "EXIST": "existing_structure",
    "E-BLDG": "existing_structure",
    "DEMOLISH": "existing_structure",
    "TREE": "tree",
    "VEGETATION": "tree",
}

# Text fragments (uppercase) → feature tag
_TEXT_FEATURE_MAP: dict[str, str] = {
    "ROAD": "road",
    "STREET": "road",
    "GALI": "road",     # Nepali/Hindi for lane
    "LANE": "road",
    "TREE": "tree",
    "PLANT": "tree",
    "DRAIN": "drain",
    "NALA": "drain",     # Nepali for drain/stream
    "KHOLA": "water_body",   # Nepali for river
    "RIVER": "water_body",
    "POND": "water_body",
    "WELL": "well",
    "BORING": "well",
    "BOREHOLE": "well",
    "WATER TABLE": "well",
}


def extract_features(doc: Drawing) -> tuple[list[str], list[str]]:
    """
    Returns:
        features : deduplicated feature tags in detection order
        notes    : extraction log
    """
    msp = doc.modelspace()
    features: list[str] = []
    notes: list[str] = []
    seen: set[str] = set()

    def _add(tag: str) -> None:
        if tag not in seen:
            seen.add(tag)
            features.append(tag)

    for entity in msp:
        dxftype = entity.dxftype()
        layer: str = (
            entity.dxf.layer.upper().strip() if entity.dxf.hasattr("layer") else ""
        )

        # ----- Block insertions -----
        if dxftype == "INSERT":
            block_name: str = entity.dxf.name.upper()
            for key, tag in _BLOCK_FEATURE_MAP.items():
                if key in block_name:
                    _add(tag)

        # ----- Layer-based detection -----
        for key, tag in _LAYER_FEATURE_MAP.items():
            if key in layer:
                _add(tag)

        # ----- Text entities -----
        if dxftype in ("TEXT", "MTEXT"):
            try:
                text = (
                    entity.plain_mtext()
                    if dxftype == "MTEXT"
                    else entity.dxf.text
                ).upper()
            except Exception:
                continue

            for key, tag in _TEXT_FEATURE_MAP.items():
                if key in text:
                    _add(tag)

    if features:
        notes.append(f"Site features detected: {', '.join(features)}")
    else:
        notes.append("No site features detected")

    return features, notes
