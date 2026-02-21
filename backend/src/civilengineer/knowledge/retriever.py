"""
ChromaDB semantic retriever.

Searches the indexed rule collection by natural-language queries.
Falls back to keyword search against the in-memory RuleSet when ChromaDB
is not available.

Usage (with ChromaDB):
    retriever = RuleRetriever(persist_dir=Path("knowledge_base/vector_store"))
    rules = retriever.search("minimum bedroom size Nepal", n_results=5)

Usage (keyword fallback — no ChromaDB required):
    retriever = RuleRetriever.from_rule_set(rule_set)
    rules = retriever.search("bedroom area")
"""

from __future__ import annotations

import logging
from pathlib import Path

from civilengineer.schemas.rules import DesignRule, RuleCategory, RuleSet

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "building_rules"
_EMBED_MODEL = "all-MiniLM-L6-v2"


class RuleRetriever:
    """
    Semantic search over building-code rules.

    Two modes:
      1. ChromaDB mode — fast vector search (requires chromadb + sentence-transformers)
      2. Keyword fallback — substring match on embedding_text (always available)
    """

    def __init__(
        self,
        persist_dir: Path | None = None,
        rule_set: RuleSet | None = None,
        model_name: str = _EMBED_MODEL,
    ) -> None:
        self._rule_set = rule_set
        self._collection = None

        if persist_dir is not None:
            try:
                import chromadb  # noqa: PLC0415
                from chromadb.utils import embedding_functions  # noqa: PLC0415

                client = chromadb.PersistentClient(path=str(persist_dir))
                embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=model_name
                )
                self._collection = client.get_collection(
                    name=_COLLECTION_NAME,
                    embedding_function=embed_fn,
                )
                logger.info(
                    "RuleRetriever: ChromaDB collection loaded (%d rules)",
                    self._collection.count(),
                )
            except Exception as exc:
                logger.warning(
                    "ChromaDB unavailable (%s); falling back to keyword search", exc
                )

    @classmethod
    def from_rule_set(cls, rule_set: RuleSet) -> RuleRetriever:
        """Create a retriever with keyword-fallback mode from a RuleSet."""
        inst = cls.__new__(cls)
        inst._rule_set = rule_set
        inst._collection = None
        return inst

    # ------------------------------------------------------------------
    # Public search API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n_results: int = 10,
        category: RuleCategory | None = None,
        jurisdiction: str | None = None,
    ) -> list[DesignRule]:
        """
        Return up to n_results rules most relevant to the query.

        If ChromaDB is available, uses vector similarity.
        Otherwise falls back to keyword matching on embedding_text.
        """
        if self._collection is not None:
            return self._chroma_search(query, n_results, category, jurisdiction)
        if self._rule_set is not None:
            return self._keyword_search(query, n_results, category, jurisdiction)
        raise RuntimeError(
            "RuleRetriever has neither a ChromaDB collection nor a RuleSet. "
            "Initialise with persist_dir or use RuleRetriever.from_rule_set()."
        )

    def get_by_room_type(
        self,
        room_type: str,
        category: RuleCategory | None = None,
    ) -> list[DesignRule]:
        """Return all rules that apply to a specific room type."""
        if self._rule_set is None:
            raise RuntimeError("get_by_room_type requires a RuleSet (keyword mode)")

        results = []
        for rule in self._rule_set.rules:
            if not rule.is_active:
                continue
            if "all" in rule.applies_to or room_type in rule.applies_to:
                if category is None or rule.category == category:
                    results.append(rule)
        return results

    # ------------------------------------------------------------------
    # Internal implementations
    # ------------------------------------------------------------------

    def _chroma_search(
        self,
        query: str,
        n_results: int,
        category: RuleCategory | None,
        jurisdiction: str | None,
    ) -> list[DesignRule]:
        where: dict = {}
        if category:
            where["category"] = {"$eq": category.value}
        if jurisdiction:
            where["jurisdiction"] = {"$eq": jurisdiction}

        kwargs: dict = {"query_texts": [query], "n_results": n_results}
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)  # type: ignore[union-attr]
        rule_ids: list[str] = results["ids"][0] if results["ids"] else []
        metadatas: list[dict] = results["metadatas"][0] if results["metadatas"] else []

        # Reconstruct minimal DesignRule objects from metadata
        rules = []
        for rule_id, meta in zip(rule_ids, metadatas):
            rules.append(
                DesignRule(
                    rule_id=rule_id,
                    jurisdiction=meta.get("jurisdiction", ""),
                    code_version=meta.get("code_version", ""),
                    category=RuleCategory(meta.get("category", "area")),
                    severity=meta.get("severity", "hard"),  # type: ignore[arg-type]
                    rule_type=meta.get("rule_type", ""),
                    name=meta.get("name", ""),
                    description="",
                    source_section=meta.get("source_section", ""),
                    applies_to=meta.get("applies_to", "").split(","),
                    numeric_value=float(v) if (v := meta.get("numeric_value")) else None,
                    unit=meta.get("unit") or None,
                    embedding_text="",
                )
            )
        return rules

    def _keyword_search(
        self,
        query: str,
        n_results: int,
        category: RuleCategory | None,
        jurisdiction: str | None,
    ) -> list[DesignRule]:
        tokens = query.lower().split()
        results: list[tuple[int, DesignRule]] = []

        for rule in self._rule_set.rules:  # type: ignore[union-attr]
            if not rule.is_active:
                continue
            if category and rule.category != category:
                continue
            if jurisdiction and rule.jurisdiction != jurisdiction:
                continue

            text = (rule.embedding_text + " " + rule.description).lower()
            score = sum(1 for t in tokens if t in text)
            if score > 0:
                results.append((score, rule))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in results[:n_results]]
