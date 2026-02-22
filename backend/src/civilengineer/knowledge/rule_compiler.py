"""
Rule compiler — loads DesignRule objects from the database or bundled JSON.

Two loading paths:
  1. load_rules_from_db(session, jurisdiction)  — DB-first (production)
     Queries JurisdictionRuleModel; falls back to load_rules() if the DB
     has no rules for the requested jurisdiction.

  2. load_rules(path, jurisdiction)              — JSON-only (tests / seed)
     Reads the bundled rules.json (or a custom path). Unchanged API.

Both return a RuleSet ready for the rule engine or ChromaDB indexer.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from civilengineer.schemas.rules import DesignRule, RuleSet

logger = logging.getLogger(__name__)

# Default bundled data file
_DEFAULT_RULES_PATH = Path(__file__).parent / "data" / "rules.json"


def _auto_embedding_text(rule: DesignRule) -> str:
    """Generate embedding text from rule fields if not provided."""
    parts = [rule.name, rule.description]
    if rule.applies_to:
        parts.append("applies to: " + ", ".join(rule.applies_to))
    if rule.tags:
        parts.append(" ".join(rule.tags))
    parts.append(rule.jurisdiction)
    parts.append(rule.code_version)
    return " ".join(parts)


def load_rules(
    path: Path | None = None,
    jurisdiction: str | None = None,
) -> RuleSet:
    """
    Load, validate, and return a RuleSet.

    Args:
        path         : Path to rules.json.  Defaults to the bundled file.
        jurisdiction : If provided, filter to only rules for this jurisdiction.

    Returns:
        RuleSet with all active rules.

    Raises:
        FileNotFoundError  : if the file does not exist
        ValueError         : if any rule fails Pydantic validation
    """
    source = path or _DEFAULT_RULES_PATH

    if not source.exists():
        raise FileNotFoundError(f"Rules file not found: {source}")

    raw: list[dict] = json.loads(source.read_text(encoding="utf-8"))
    rules: list[DesignRule] = []
    skipped = 0

    for i, record in enumerate(raw):
        try:
            rule = DesignRule.model_validate(record)
            if not rule.embedding_text:
                rule = rule.model_copy(
                    update={"embedding_text": _auto_embedding_text(rule)}
                )
            if jurisdiction and rule.jurisdiction != jurisdiction:
                continue
            rules.append(rule)
        except Exception as exc:
            logger.warning("Skipping rule at index %d: %s", i, exc)
            skipped += 1

    if not rules:
        raise ValueError(f"No valid rules loaded from {source}")

    active = [r for r in rules if r.is_active]
    logger.info(
        "Loaded %d rules (%d active, %d skipped) from %s",
        len(rules),
        len(active),
        skipped,
        source.name,
    )

    # All rules share the same jurisdiction/code_version in our bundled file
    jurisdiction_val = rules[0].jurisdiction
    code_version_val = rules[0].code_version

    return RuleSet(
        jurisdiction=jurisdiction_val,
        code_version=code_version_val,
        rules=active,
    )


# ---------------------------------------------------------------------------
# DB-first loading
# ---------------------------------------------------------------------------


async def load_rules_from_db(
    session: object,  # AsyncSession — typed loosely to avoid hard import
    jurisdiction: str,
    code_version: str | None = None,
) -> RuleSet:
    """
    Load active rules from JurisdictionRuleModel for a given jurisdiction.

    Falls back to load_rules(jurisdiction=jurisdiction) when the DB has no
    matching rules (e.g. fresh environment before seeding, or unit tests
    that don't have a database).

    Args:
        session      : SQLAlchemy AsyncSession (from get_session or AsyncSessionLocal).
        jurisdiction : e.g. "NP-KTM", "IN-MH", "US-CA".
        code_version : Optional version filter (e.g. "NBC_2020").

    Returns:
        RuleSet containing all active DesignRule objects.
    """
    # Import lazily so the compiler is importable without SQLAlchemy installed
    from civilengineer.db.repositories.rule_repository import (  # noqa: PLC0415
        get_active_rules,
        model_to_design_rule,
    )

    try:
        models = await get_active_rules(session, jurisdiction, code_version)
    except Exception as exc:
        logger.warning(
            "load_rules_from_db: DB query failed (%s); falling back to bundled JSON.",
            exc,
        )
        return load_rules(jurisdiction=jurisdiction)

    if not models:
        logger.warning(
            "load_rules_from_db: no active rules in DB for jurisdiction=%s; "
            "falling back to bundled JSON.",
            jurisdiction,
        )
        return load_rules(jurisdiction=jurisdiction)

    rules: list[DesignRule] = []
    for m in models:
        rule = model_to_design_rule(m)
        if not rule.embedding_text:
            rule = rule.model_copy(
                update={"embedding_text": _auto_embedding_text(rule)}
            )
        rules.append(rule)

    active = [r for r in rules if r.is_active]
    logger.info(
        "load_rules_from_db: loaded %d active rules for %s from database.",
        len(active),
        jurisdiction,
    )

    code_ver = models[0].code_version if models else (code_version or "")
    return RuleSet(jurisdiction=jurisdiction, code_version=code_ver, rules=active)
