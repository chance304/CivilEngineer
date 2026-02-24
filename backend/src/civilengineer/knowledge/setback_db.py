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

  IN-MH    Mumbai / Maharashtra (DCPR 2034)
  IN-MH-PUN Pune (PMC Development Plan 2007)
  IN-KA    Bangalore / Karnataka (BDA Master Plan 2031)
  IN       Generic India (NBC 2016 defaults)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Road-width category breakpoints (metres)
# ---------------------------------------------------------------------------

def _road_category(road_width_m: float | None) -> str:
    """Classify road width using Nepal/default breakpoints (KMC Bylaw 2076)."""
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


def _road_category_india(road_width_m: float | None) -> str:
    """Classify road width using Indian jurisdiction breakpoints (DCPR 2034 / BDA / NBC 2016)."""
    if road_width_m is None:
        return "unknown"
    if road_width_m < 9.0:
        return "narrow"       # < 9 m
    if road_width_m < 12.0:
        return "local"        # 9–12 m
    if road_width_m < 18.0:
        return "collector"    # 12–18 m
    if road_width_m < 30.0:
        return "arterial"     # 18–30 m
    return "highway"          # ≥ 30 m


def _road_category_for_code(road_width_m: float | None, city_code: str) -> str:
    """Select road category using jurisdiction-appropriate breakpoints."""
    if city_code[:2].upper() == "IN":
        return _road_category_india(road_width_m)
    return _road_category(road_width_m)


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

    # ------- Mumbai / Maharashtra (DCPR 2034) -------
    # Road-width thresholds per DCPR 2034 Regulation 23
    "IN-MH": {
        "narrow":    SetbackRecord(3.0, 3.0, 1.5, 1.5, "DCPR 2034 Reg 23 — road <9m"),
        "local":     SetbackRecord(4.5, 3.0, 1.5, 1.5, "DCPR 2034 Reg 23 — road 9–12m"),
        "collector": SetbackRecord(6.0, 3.0, 3.0, 3.0, "DCPR 2034 Reg 23 — road 12–18m"),
        "arterial":  SetbackRecord(9.0, 4.5, 4.5, 4.5, "DCPR 2034 Reg 23 — road 18–30m"),
        "highway":   SetbackRecord(12.0, 6.0, 6.0, 6.0, "DCPR 2034 Reg 23 — road >30m"),
        "unknown":   SetbackRecord(3.0, 3.0, 1.5, 1.5, "DCPR 2034 default"),
    },

    # ------- Pune (PMC Development Plan 2007, revised 2017) -------
    "IN-MH-PUN": {
        "narrow":    SetbackRecord(3.0, 1.5, 1.5, 1.5, "PMC DP 2007 §6.3 — road <9m"),
        "local":     SetbackRecord(4.5, 3.0, 1.5, 1.5, "PMC DP 2007 §6.3 — road 9–12m"),
        "collector": SetbackRecord(6.0, 3.0, 3.0, 3.0, "PMC DP 2007 §6.3 — road 12–18m"),
        "arterial":  SetbackRecord(9.0, 4.5, 4.5, 4.5, "PMC DP 2007 §6.3 — road 18–30m"),
        "highway":   SetbackRecord(12.0, 6.0, 6.0, 6.0, "NBC 2016 Part 6 §1.2"),
        "unknown":   SetbackRecord(3.0, 1.5, 1.5, 1.5, "PMC DP 2007 default"),
    },

    # ------- Bangalore / Karnataka (BDA Master Plan 2031) -------
    "IN-KA": {
        "narrow":    SetbackRecord(2.0, 2.0, 1.2, 1.2, "BDA MP 2031 §8.4 — road <9m"),
        "local":     SetbackRecord(3.0, 2.0, 1.5, 1.5, "BDA MP 2031 §8.4 — road 9–12m"),
        "collector": SetbackRecord(4.5, 3.0, 2.25, 2.25, "BDA MP 2031 §8.4 — road 12–18m"),
        "arterial":  SetbackRecord(6.0, 3.0, 3.0, 3.0, "BDA MP 2031 §8.4 — road 18–30m"),
        "highway":   SetbackRecord(9.0, 4.5, 4.5, 4.5, "BDA MP 2031 §8.4 — road >30m"),
        "unknown":   SetbackRecord(2.0, 2.0, 1.2, 1.2, "BDA MP 2031 default"),
    },

    # ------- Generic India (NBC 2016 Part 6 defaults) -------
    "IN": {
        "narrow":    SetbackRecord(2.5, 2.5, 1.5, 1.5, "NBC 2016 Part 6 §1.2 — narrow"),
        "local":     SetbackRecord(3.0, 3.0, 1.5, 1.5, "NBC 2016 Part 6 §1.2 — local"),
        "collector": SetbackRecord(4.5, 3.0, 2.25, 2.25, "NBC 2016 Part 6 §1.2 — collector"),
        "arterial":  SetbackRecord(6.0, 4.5, 3.0, 3.0, "NBC 2016 Part 6 §1.2 — arterial"),
        "highway":   SetbackRecord(9.0, 6.0, 4.5, 4.5, "NBC 2016 Part 6 §1.2 — highway"),
        "unknown":   SetbackRecord(2.5, 2.5, 1.5, 1.5, "NBC 2016 default"),
    },
}

# City name aliases → canonical code
_CITY_ALIASES: dict[str, str] = {
    # Nepal
    "kathmandu":      "NP-KTM",
    "ktm":            "NP-KTM",
    "np-ktm":         "NP-KTM",
    "pokhara":        "NP-PKR",
    "pkr":            "NP-PKR",
    "np-pkr":         "NP-PKR",
    "lalitpur":       "NP-LAL",
    "patan":          "NP-LAL",
    "np-lal":         "NP-LAL",
    "bhaktapur":      "NP-BKT",
    "bkt":            "NP-BKT",
    "np-bkt":         "NP-BKT",
    "nepal":          "NP",
    "np":             "NP",
    # India — Maharashtra / Mumbai
    "mumbai":         "IN-MH",
    "maharashtra":    "IN-MH",
    "in-mh":          "IN-MH",
    "greater mumbai": "IN-MH",
    "navi mumbai":    "IN-MH",
    "thane":          "IN-MH",
    # India — Pune
    "pune":           "IN-MH-PUN",
    "in-mh-pun":      "IN-MH-PUN",
    "pimpri":         "IN-MH-PUN",
    # India — Karnataka / Bangalore
    "bangalore":      "IN-KA",
    "bengaluru":      "IN-KA",
    "in-ka":          "IN-KA",
    "mysore":         "IN-KA",
    "mysuru":         "IN-KA",
    # Generic India
    "india":          "IN",
    "in":             "IN",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _guess_fallback_table(code: str) -> dict[str, SetbackRecord]:
    """
    Pick the best generic fallback for an unrecognised city code.

    Uses the two-letter country prefix to select a country-level default.
    Falls back to Nepal (NP) for unrecognised prefixes.
    """
    prefix = code[:2].upper()
    if prefix == "IN":
        return _SETBACK_TABLE["IN"]
    return _SETBACK_TABLE["NP"]


class SetbackDB:
    """
    Look up setback requirements by city and road width.

    Priority:
      1. Database (JurisdictionRuleModel) — when session is provided
      2. Hardcoded table (_SETBACK_TABLE) — always available as fallback

    Pass a SQLAlchemy AsyncSession as ``session`` to enable DB lookup.
    Without a session the behaviour is identical to the previous version.
    """

    def get_setbacks(
        self,
        city: str,
        road_width_m: float | None = None,
        *,
        session: object | None = None,
    ) -> tuple[float, float, float, float]:
        """
        Return (front, rear, left, right) setbacks in metres.

        Args:
            city:         City name or code (case-insensitive).
            road_width_m: Front road width in metres (None = default category).
            session:      Optional AsyncSession. When provided, DB is queried first.
                          Must be used inside an async context (caller must await
                          _db_lookup separately if needed; sync callers get fallback).
        """
        # Sync callers (and callers without a session) use the hardcoded table.
        # Async DB lookup is exposed via get_setbacks_async().
        code = _CITY_ALIASES.get(city.lower(), city.upper())
        city_table = _SETBACK_TABLE.get(code) or _guess_fallback_table(code)
        category = _road_category_for_code(road_width_m, code)
        record = city_table.get(category) or city_table.get("unknown")

        if record is None:
            logger.warning(
                "No setback record for city=%s category=%s; using 1.5m default.",
                city, category,
            )
            return (1.5, 1.5, 1.0, 1.0)

        logger.debug(
            "SetbackDB: city=%s road=%.1fm cat=%s → front=%.1f rear=%.1f "
            "side=%.1f/%.1f [%s]",
            code, road_width_m or 0, category,
            record.front, record.rear, record.left, record.right, record.source,
        )
        return (record.front, record.rear, record.left, record.right)

    async def get_setbacks_async(
        self,
        city: str,
        road_width_m: float | None = None,
        *,
        session: object | None = None,
    ) -> tuple[float, float, float, float]:
        """
        Async version of get_setbacks — tries the DB first when session is given.

        DB rules take priority if matching rules exist (jurisdiction + category);
        falls back to the hardcoded table transparently.
        """
        if session is not None:
            db_result = await self._db_lookup(session, city, road_width_m)
            if db_result is not None:
                return db_result
        return self.get_setbacks(city, road_width_m)

    async def _db_lookup(
        self,
        session: object,
        city: str,
        road_width_m: float | None,
    ) -> tuple[float, float, float, float] | None:
        """
        Query JurisdictionRuleModel for setback rules matching the city and road width.

        Looks for setback rules where:
          - jurisdiction == canonical city code
          - category == "setback"
          - conditions["road_category"] matches the computed road category

        Returns None if no matching DB rules are found.
        """
        try:
            from civilengineer.db.repositories.rule_repository import (  # noqa: PLC0415
                get_active_rules,
            )
            from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415
        except ImportError:
            return None

        code = _CITY_ALIASES.get(city.lower(), city.upper())
        category = _road_category_for_code(road_width_m, code)

        try:
            rules = await get_active_rules(session, jurisdiction=code)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("SetbackDB._db_lookup failed: %s", exc)
            return None

        # Filter to setback rules matching this road category
        front = rear = left = right = None
        for rule in rules:
            if rule.category.value != "setback":
                continue
            rule_cat = rule.conditions.get("road_category")
            if rule_cat and rule_cat != category:
                continue
            if rule.numeric_value is None:
                continue
            rt = rule.rule_type
            if rt == "min_setback_front":
                front = rule.numeric_value
            elif rt == "min_setback_rear":
                rear = rule.numeric_value
            elif rt == "min_setback_side":
                left = right = rule.numeric_value

        if front is not None and rear is not None and left is not None:
            logger.debug(
                "SetbackDB: DB hit city=%s cat=%s → front=%.1f rear=%.1f side=%.1f/%.1f",
                code, category, front, rear, left, right,
            )
            return (front, rear, left, right)  # type: ignore[return-value]

        return None

    def get_record(
        self,
        city: str,
        road_width_m: float | None = None,
    ) -> SetbackRecord:
        """Return the full SetbackRecord including citation."""
        code = _CITY_ALIASES.get(city.lower(), city.upper())
        city_table = _SETBACK_TABLE.get(code) or _guess_fallback_table(code)
        category = _road_category_for_code(road_width_m, code)
        return city_table.get(category) or city_table["unknown"]

    def supported_cities(self) -> list[str]:
        """Return all canonical city codes."""
        return list(_SETBACK_TABLE.keys())

    def road_category(self, road_width_m: float | None) -> str:
        """Expose road-category classification."""
        return _road_category(road_width_m)
