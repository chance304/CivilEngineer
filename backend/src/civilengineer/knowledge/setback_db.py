"""
City setback database.

Stores front / rear / left / right setbacks (metres) for specific cities
and road-width categories, based on local municipal bylaws.

Hierarchy:
  1. City-specific rules (highest priority)
  2. Regional fallback (Nepal generic)
  3. Rules.json enricher (lowest priority — used by Enricher)

Usage
-----
    from civilengineer.knowledge.setback_db import SetbackDB

    db = SetbackDB()
    front, rear, left, right = db.get_setbacks("Kathmandu", road_width_m=7.0)

Supported cities:
  NP-KTM   Kathmandu (KMC Bylaw 2076 + NBC 2020)
  NP-PKR   Pokhara   (PMC Bylaw 2076)
  NP-LAL   Lalitpur  (LMCB 2076)
  NP-BKT   Bhaktapur (BMCB 2076)
  NP       Generic Nepal (NBC 2020 defaults)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Road-width category breakpoints (metres)
# ---------------------------------------------------------------------------

def _road_category(road_width_m: float | None) -> str:
    """Classify road width into a named category."""
    if road_width_m is None:
        return "unknown"
    if road_width_m < 6.0:
        return "narrow"       # < 6 m
    if road_width_m < 8.0:
        return "local"        # 6–8 m
    if road_width_m < 11.0:
        return "collector"    # 8–11 m
    if road_width_m < 20.0:
        return "arterial"     # 11–20 m
    return "highway"          # ≥ 20 m


# ---------------------------------------------------------------------------
# Setback record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SetbackRecord:
    front: float   # metres
    rear: float
    left: float
    right: float
    source: str    # human-readable citation


# ---------------------------------------------------------------------------
# City × road-category → setback table
# (front, rear, left, right) in metres
# ---------------------------------------------------------------------------

_SETBACK_TABLE: dict[str, dict[str, SetbackRecord]] = {
    # ------- Kathmandu (KMC Bylaw 2076 / NBC 205:2020) -------
    "NP-KTM": {
        "narrow":    SetbackRecord(1.5, 1.5, 1.0, 1.0, "KMC Bylaw 2076 §7.2"),
        "local":     SetbackRecord(1.5, 1.5, 1.0, 1.0, "KMC Bylaw 2076 §7.2"),
        "collector": SetbackRecord(2.0, 1.5, 1.5, 1.5, "KMC Bylaw 2076 §7.3"),
        "arterial":  SetbackRecord(3.0, 2.0, 1.5, 1.5, "KMC Bylaw 2076 §7.4"),
        "highway":   SetbackRecord(5.0, 3.0, 2.0, 2.0, "NBC 205:2020 §8.1"),
        "unknown":   SetbackRecord(1.5, 1.5, 1.0, 1.0, "KMC Bylaw 2076 default"),
    },
    # ------- Pokhara (PMC Bylaw 2076) -------
    "NP-PKR": {
        "narrow":    SetbackRecord(1.5, 1.5, 1.0, 1.0, "PMC Bylaw 2076 §6.1"),
        "local":     SetbackRecord(2.0, 1.5, 1.0, 1.0, "PMC Bylaw 2076 §6.2"),
        "collector": SetbackRecord(3.0, 1.5, 1.5, 1.5, "PMC Bylaw 2076 §6.3"),
        "arterial":  SetbackRecord(4.0, 2.0, 1.5, 1.5, "PMC Bylaw 2076 §6.4"),
        "highway":   SetbackRecord(6.0, 3.0, 2.0, 2.0, "NBC 205:2020 §8.1"),
        "unknown":   SetbackRecord(1.5, 1.5, 1.0, 1.0, "PMC Bylaw 2076 default"),
    },
    # ------- Lalitpur (LMCB 2076) -------
    "NP-LAL": {
        "narrow":    SetbackRecord(1.5, 1.5, 1.0, 1.0, "LMCB 2076 §5.1"),
        "local":     SetbackRecord(2.0, 1.5, 1.0, 1.0, "LMCB 2076 §5.2"),
        "collector": SetbackRecord(2.5, 1.5, 1.5, 1.5, "LMCB 2076 §5.3"),
        "arterial":  SetbackRecord(3.5, 2.0, 1.5, 1.5, "LMCB 2076 §5.4"),
        "highway":   SetbackRecord(5.0, 3.0, 2.0, 2.0, "NBC 205:2020 §8.1"),
        "unknown":   SetbackRecord(1.5, 1.5, 1.0, 1.0, "LMCB 2076 default"),
    },
    # ------- Bhaktapur (BMCB 2076) -------
    "NP-BKT": {
        "narrow":    SetbackRecord(1.5, 1.5, 1.0, 1.0, "BMCB 2076 §4.1"),
        "local":     SetbackRecord(2.0, 1.5, 1.0, 1.0, "BMCB 2076 §4.2"),
        "collector": SetbackRecord(2.5, 1.5, 1.5, 1.5, "BMCB 2076 §4.3"),
        "arterial":  SetbackRecord(3.0, 2.0, 1.5, 1.5, "BMCB 2076 §4.4"),
        "highway":   SetbackRecord(5.0, 3.0, 2.0, 2.0, "NBC 205:2020 §8.1"),
        "unknown":   SetbackRecord(1.5, 1.5, 1.0, 1.0, "BMCB 2076 default"),
    },
    # ------- Generic Nepal (NBC 205:2020 defaults) -------
    "NP": {
        "narrow":    SetbackRecord(1.5, 1.5, 1.0, 1.0, "NBC 205:2020 §7.1"),
        "local":     SetbackRecord(2.0, 1.5, 1.0, 1.0, "NBC 205:2020 §7.2"),
        "collector": SetbackRecord(3.0, 1.5, 1.5, 1.5, "NBC 205:2020 §7.3"),
        "arterial":  SetbackRecord(4.0, 2.0, 2.0, 2.0, "NBC 205:2020 §7.4"),
        "highway":   SetbackRecord(6.0, 3.0, 2.0, 2.0, "NBC 205:2020 §8.1"),
        "unknown":   SetbackRecord(1.5, 1.5, 1.0, 1.0, "NBC 205:2020 default"),
    },
}

# City name aliases → canonical code
_CITY_ALIASES: dict[str, str] = {
    "kathmandu": "NP-KTM",
    "ktm":       "NP-KTM",
    "np-ktm":    "NP-KTM",
    "pokhara":   "NP-PKR",
    "pkr":       "NP-PKR",
    "np-pkr":    "NP-PKR",
    "lalitpur":  "NP-LAL",
    "patan":     "NP-LAL",
    "np-lal":    "NP-LAL",
    "bhaktapur": "NP-BKT",
    "bkt":       "NP-BKT",
    "np-bkt":    "NP-BKT",
    "nepal":     "NP",
    "np":        "NP",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class SetbackDB:
    """
    Look up setback requirements by city and road width.

    Falls back gracefully through: city-specific → Nepal generic → hardcoded minimum.
    """

    def get_setbacks(
        self,
        city: str,
        road_width_m: float | None = None,
    ) -> tuple[float, float, float, float]:
        """
        Return (front, rear, left, right) setbacks in metres.

        Args:
            city:         City name or code (case-insensitive). E.g. "Kathmandu", "NP-KTM".
            road_width_m: Front road width in metres (None = use default category).
        """
        code = _CITY_ALIASES.get(city.lower(), "NP")
        city_table = _SETBACK_TABLE.get(code) or _SETBACK_TABLE["NP"]
        category = _road_category(road_width_m)
        record = city_table.get(category) or city_table.get("unknown")

        if record is None:
            logger.warning("No setback record for city=%s category=%s; using 1.5m default.", city, category)
            return (1.5, 1.5, 1.0, 1.0)

        logger.debug(
            "SetbackDB: city=%s road=%.1fm cat=%s → front=%.1f rear=%.1f side=%.1f/%.1f [%s]",
            code, road_width_m or 0, category,
            record.front, record.rear, record.left, record.right, record.source,
        )
        return (record.front, record.rear, record.left, record.right)

    def get_record(
        self,
        city: str,
        road_width_m: float | None = None,
    ) -> SetbackRecord:
        """Return the full SetbackRecord including citation."""
        code = _CITY_ALIASES.get(city.lower(), "NP")
        city_table = _SETBACK_TABLE.get(code) or _SETBACK_TABLE["NP"]
        category = _road_category(road_width_m)
        return city_table.get(category) or city_table["unknown"]

    def supported_cities(self) -> list[str]:
        """Return all canonical city codes."""
        return list(_SETBACK_TABLE.keys())

    def road_category(self, road_width_m: float | None) -> str:
        """Expose road-category classification."""
        return _road_category(road_width_m)
