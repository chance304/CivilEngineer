"""
Rule compiler — loads and validates rules.json into DesignRule objects.

The compiler:
  1. Reads the bundled JSON file (or a custom path)
  2. Validates every record with the DesignRule Pydantic model
  3. Auto-generates embedding_text if the field is empty
  4. Returns a RuleSet ready for the rule engine or ChromaDB indexer
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
