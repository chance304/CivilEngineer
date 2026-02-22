"""
ChromaDB knowledge indexer.

Embeds rules with sentence-transformers (all-MiniLM-L6-v2) and stores them
in a persistent ChromaDB collection.

Heavy dependencies (chromadb, sentence-transformers) are imported lazily so
that other modules remain importable even without them installed.

Usage:
    from civilengineer.knowledge.indexer import build_index
    build_index(rule_set, persist_dir=Path("knowledge_base/vector_store"))
"""

from __future__ import annotations

import logging
from pathlib import Path

from civilengineer.schemas.rules import RuleSet

logger = logging.getLogger(__name__)

# ChromaDB collection name
_COLLECTION_NAME = "building_rules"
# Embedding model — lightweight, CPU-friendly
_EMBED_MODEL = "all-MiniLM-L6-v2"


def _get_chroma_client(persist_dir: Path):
    try:
        import chromadb  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "chromadb is required for indexing. Install it: uv pip install chromadb"
        ) from exc
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def _get_embedding_fn(model_name: str):
    try:
        from chromadb.utils import embedding_functions  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "chromadb is required for embeddings. Install it: uv pip install chromadb"
        ) from exc
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_name
    )


def build_index(
    rule_set: RuleSet,
    persist_dir: Path | None = None,
    model_name: str = _EMBED_MODEL,
    reset: bool = False,
) -> None:
    """
    Embed all rules in rule_set and upsert them into ChromaDB.

    Args:
        rule_set    : RuleSet loaded by rule_compiler.load_rules()
        persist_dir : Where ChromaDB stores its files.
                      Defaults to knowledge_base/vector_store/ relative to cwd.
        model_name  : Sentence-transformers model for embeddings.
        reset       : If True, delete the collection before re-indexing.
    """
    if persist_dir is None:
        persist_dir = Path("knowledge_base") / "vector_store"

    logger.info("Building ChromaDB index in %s", persist_dir)

    client = _get_chroma_client(persist_dir)
    embed_fn = _get_embedding_fn(model_name)

    if reset:
        try:
            client.delete_collection(_COLLECTION_NAME)
            logger.info("Deleted existing collection '%s'", _COLLECTION_NAME)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    rules = rule_set.rules
    if not rules:
        logger.warning("No rules to index")
        return

    ids = [r.rule_id for r in rules]
    # documents holds the text that gets embedded (embedding_text field)
    documents = [r.embedding_text or r.name for r in rules]
    metadatas = [
        {
            # Scalar metadata for ChromaDB where-clause filtering
            "jurisdiction": r.jurisdiction,
            "code_version": r.code_version,
            "category": r.category.value,
            "severity": r.severity.value,
            "rule_type": r.rule_type,
            "applies_to": ",".join(r.applies_to),
            "numeric_value": r.numeric_value if r.numeric_value is not None else "",
            "unit": r.unit or "",
            "source_section": r.source_section,
            "name": r.name,
            # Full rule as JSON — enables lossless round-trip in retriever
            "full_rule_json": r.model_dump_json(),
        }
        for r in rules
    ]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    logger.info("Indexed %d rules into collection '%s'", len(rules), _COLLECTION_NAME)


def get_collection_stats(persist_dir: Path | None = None) -> dict:
    """Return basic stats about the indexed collection."""
    if persist_dir is None:
        persist_dir = Path("knowledge_base") / "vector_store"

    client = _get_chroma_client(persist_dir)
    try:
        col = client.get_collection(_COLLECTION_NAME)
        return {
            "collection": _COLLECTION_NAME,
            "count": col.count(),
            "persist_dir": str(persist_dir),
        }
    except Exception as exc:
        return {"error": str(exc)}
