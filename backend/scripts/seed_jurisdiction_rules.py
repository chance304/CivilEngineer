"""
Seed jurisdiction rules into the database from three bundled sources:

  1. rules.json        — main building-code rules (area, FAR, height, etc.)
  2. setback_db.py     — city-specific setback rules per road-width category
  3. constraint_solver — room dimension defaults (_DEFAULT_DIMS / _MIN_DIM)

All inserts are idempotent: existing rules are updated in place (upsert).

Usage
-----
    # From backend/ directory:
    uv run python scripts/seed_jurisdiction_rules.py
    uv run python scripts/seed_jurisdiction_rules.py --jurisdiction NP-KTM
    uv run python scripts/seed_jurisdiction_rules.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add src/ to path so we can import civilengineer without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import structlog

from civilengineer.db.repositories import rule_repository
from civilengineer.db.session import AsyncSessionLocal
from civilengineer.knowledge.rule_compiler import load_rules
from civilengineer.knowledge.setback_db import _CITY_ALIASES, _SETBACK_TABLE
from civilengineer.reasoning_engine.constraint_solver import _DEFAULT_DIMS, _MIN_DIM
from civilengineer.schemas.rules import DesignRule, RuleCategory, Severity

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Setback rule generation
# ---------------------------------------------------------------------------

def _setback_rules_for_jurisdiction(
    jurisdiction: str,
) -> list[DesignRule]:
    """
    Convert _SETBACK_TABLE entries for a jurisdiction into DesignRule objects.

    Three rules are produced per road-category (front, rear, side), each
    carrying conditions={"road_category": cat} so the rule engine and
    solver can match them correctly.
    """
    table = _SETBACK_TABLE.get(jurisdiction)
    if table is None:
        return []

    # Choose a plausible code_version for this jurisdiction
    code_version_map = {
        "NP-KTM": "NBC_2020",
        "NP-PKR": "NBC_2020",
        "NP-LAL": "NBC_2020",
        "NP-BKT": "NBC_2020",
        "NP":     "NBC_2020",
    }
    code_version = code_version_map.get(jurisdiction, "LOCAL_BYLAW")

    rules: list[DesignRule] = []
    jur_slug = jurisdiction.replace("-", "_")

    for cat, record in table.items():
        cat_slug = cat.upper()
        source = record.source

        for direction, value, rule_type, rule_suffix in [
            ("front", record.front, "min_setback_front", "FRONT"),
            ("rear",  record.rear,  "min_setback_rear",  "REAR"),
            ("side",  record.left,  "min_setback_side",  "SIDE"),
        ]:
            rule_id = f"{jur_slug}_SETBACK_{rule_suffix}_{cat_slug}"
            rules.append(
                DesignRule(
                    rule_id=rule_id,
                    jurisdiction=jurisdiction,
                    code_version=code_version,
                    category=RuleCategory.SETBACK,
                    severity=Severity.HARD,
                    rule_type=rule_type,
                    name=f"Min {direction} setback ({cat} road)",
                    description=(
                        f"Minimum {direction} setback of {value} m for {cat} roads "
                        f"in {jurisdiction}."
                    ),
                    source_section=source,
                    applies_to=["all"],
                    numeric_value=value,
                    unit="m",
                    conditions={"road_category": cat},
                    tags=["setback", direction, cat],
                    embedding_text=(
                        f"minimum {direction} setback {value} metres {cat} road "
                        f"{jurisdiction} {source}"
                    ),
                    is_active=True,
                )
            )

    return rules


# ---------------------------------------------------------------------------
# Room dimension default rule generation
# ---------------------------------------------------------------------------

def _room_dim_rules(jurisdiction: str, code_version: str) -> list[DesignRule]:
    """
    Convert _DEFAULT_DIMS and _MIN_DIM from constraint_solver into DesignRule objects.

    rule_type="room_default_dim" with conditions={"width": w, "depth": d}.
    These soft rules let the solver load target dimensions from the DB rather
    than from the hardcoded Python dict.
    """
    rules: list[DesignRule] = []
    jur_slug = jurisdiction.replace("-", "_")

    for room_type, (width, depth) in _DEFAULT_DIMS.items():
        rtype_str = room_type.value
        rtype_slug = rtype_str.upper()
        min_dim = _MIN_DIM.get(room_type)

        rule_id = f"{jur_slug}_DIM_{rtype_slug}"
        description = (
            f"Default room dimensions for {rtype_str}: {width}m × {depth}m "
            f"({width * depth:.2f} sqm target)."
        )
        if min_dim:
            description += f" Minimum shorter dimension: {min_dim} m."

        conditions: dict = {"width": width, "depth": depth}
        if min_dim is not None:
            conditions["min_dim"] = min_dim

        rules.append(
            DesignRule(
                rule_id=rule_id,
                jurisdiction=jurisdiction,
                code_version=code_version,
                category=RuleCategory.AREA,
                severity=Severity.SOFT,
                rule_type="room_default_dim",
                name=f"Default dimensions for {rtype_str.replace('_', ' ').title()}",
                description=description,
                source_section="NBC 205:2020 / solver defaults",
                applies_to=[rtype_str],
                numeric_value=round(width * depth, 2),   # target area
                unit="sqm",
                conditions=conditions,
                tags=["dimensions", "default", rtype_str],
                embedding_text=(
                    f"default room dimensions {rtype_str} width {width} depth {depth} "
                    f"{jurisdiction}"
                ),
                is_active=True,
            )
        )

    return rules


# ---------------------------------------------------------------------------
# Seeding passes
# ---------------------------------------------------------------------------

async def seed_json_rules(
    session: object,
    jurisdiction: str | None,
    dry_run: bool,
) -> int:
    """Seed rules from the bundled rules.json."""
    rule_set = load_rules(jurisdiction=jurisdiction)
    count = 0
    for rule in rule_set.rules:
        if dry_run:
            logger.info("[DRY RUN] Would upsert rule: %s", rule.rule_id)
        else:
            await rule_repository.upsert_rule(session, rule)  # type: ignore[arg-type]
        count += 1
    return count


async def seed_setback_rules(
    session: object,
    jurisdiction: str | None,
    dry_run: bool,
) -> int:
    """Seed setback rules from the hardcoded _SETBACK_TABLE."""
    jurisdictions = (
        [jurisdiction] if jurisdiction
        else list({v for v in _CITY_ALIASES.values()})
    )
    count = 0
    for jur in sorted(set(jurisdictions)):
        rules = _setback_rules_for_jurisdiction(jur)
        for rule in rules:
            if dry_run:
                logger.info("[DRY RUN] Would upsert setback rule: %s", rule.rule_id)
            else:
                await rule_repository.upsert_rule(session, rule)  # type: ignore[arg-type]
            count += 1
    return count


async def seed_dim_rules(
    session: object,
    jurisdiction: str | None,
    dry_run: bool,
) -> int:
    """Seed room dimension default rules from constraint_solver constants."""
    # Dimension rules are seeded per jurisdiction; NP-KTM / NBC_2020 is the MVP default.
    targets: list[tuple[str, str]]
    if jurisdiction:
        code_ver = "NBC_2020" if jurisdiction.startswith("NP") else "LOCAL_CODE"
        targets = [(jurisdiction, code_ver)]
    else:
        targets = [
            ("NP-KTM", "NBC_2020"),
            ("NP-PKR", "NBC_2020"),
            ("NP-LAL", "NBC_2020"),
            ("NP-BKT", "NBC_2020"),
            ("NP",     "NBC_2020"),
        ]

    count = 0
    for jur, code_ver in targets:
        for rule in _room_dim_rules(jur, code_ver):
            if dry_run:
                logger.info("[DRY RUN] Would upsert dim rule: %s", rule.rule_id)
            else:
                await rule_repository.upsert_rule(session, rule)  # type: ignore[arg-type]
            count += 1
    return count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run(jurisdiction: str | None, dry_run: bool) -> None:
    label = jurisdiction or "all"
    logger.info("Seeding jurisdiction rules: %s (dry_run=%s)", label, dry_run)

    if dry_run:
        session = None  # type: ignore[assignment]
        j_rules = await seed_json_rules(session, jurisdiction, dry_run=True)
        s_rules = await seed_setback_rules(session, jurisdiction, dry_run=True)
        d_rules = await seed_dim_rules(session, jurisdiction, dry_run=True)
    else:
        async with AsyncSessionLocal() as session:
            j_rules = await seed_json_rules(session, jurisdiction, dry_run=False)
            s_rules = await seed_setback_rules(session, jurisdiction, dry_run=False)
            d_rules = await seed_dim_rules(session, jurisdiction, dry_run=False)
            await session.commit()

    logger.info(
        "Done: %d JSON rules, %d setback rules, %d dimension rules (total %d).",
        j_rules, s_rules, d_rules, j_rules + s_rules + d_rules,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed jurisdiction rules into PostgreSQL.")
    parser.add_argument(
        "--jurisdiction", "-j",
        default=None,
        help="Jurisdiction code to seed (e.g. NP-KTM). Defaults to all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be seeded without touching the database.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.jurisdiction, args.dry_run))


if __name__ == "__main__":
    main()
