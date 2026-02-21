"""
Knowledge base indexer CLI.

Loads rules.json → embeds with sentence-transformers → stores in ChromaDB.

Usage (from backend/ directory):
    python scripts/index_knowledge.py
    python scripts/index_knowledge.py --reset          # Rebuild from scratch
    python scripts/index_knowledge.py --stats          # Print index stats
    python scripts/index_knowledge.py --path /path/to/rules.json

Requires: chromadb, sentence-transformers
    uv pip install chromadb sentence-transformers
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from civilengineer.knowledge.rule_compiler import load_rules

console = Console()
app = typer.Typer()

DEFAULT_VECTOR_STORE = Path("knowledge_base") / "vector_store"


@app.command()
def main(
    rules_path: Path = typer.Option(
        None,
        "--path",
        help="Path to rules.json (defaults to bundled file)",
    ),
    vector_store: Path = typer.Option(
        DEFAULT_VECTOR_STORE,
        "--vector-store",
        help="ChromaDB persist directory",
    ),
    reset: bool = typer.Option(False, "--reset", help="Delete and rebuild the index"),
    stats: bool = typer.Option(False, "--stats", help="Print collection stats and exit"),
) -> None:
    """Build or inspect the ChromaDB knowledge index."""

    if stats:
        _print_stats(vector_store)
        return

    try:
        from civilengineer.knowledge.indexer import build_index, get_collection_stats  # noqa: PLC0415
    except ImportError:
        console.print(
            "[red]chromadb not installed.[/red]\n"
            "Run: [cyan]uv pip install chromadb sentence-transformers[/cyan]"
        )
        raise typer.Exit(1)

    # Load rules
    console.print("[bold]Loading rules...[/bold]")
    try:
        rule_set = load_rules(path=rules_path)
    except Exception as exc:
        console.print(f"[red]Failed to load rules: {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"  Loaded [green]{len(rule_set.rules)}[/green] active rules")
    console.print(f"  Jurisdiction: [cyan]{rule_set.jurisdiction}[/cyan]")
    console.print(f"  Code version: [cyan]{rule_set.code_version}[/cyan]")

    if reset:
        console.print("[yellow]--reset: rebuilding index from scratch[/yellow]")

    # Build index
    console.print(f"\n[bold]Indexing into {vector_store}...[/bold]")
    try:
        build_index(rule_set, persist_dir=vector_store, reset=reset)
    except Exception as exc:
        console.print(f"[red]Indexing failed: {exc}[/red]")
        raise typer.Exit(1)

    # Show stats
    _print_stats(vector_store)


def _print_stats(vector_store: Path) -> None:
    try:
        from civilengineer.knowledge.indexer import get_collection_stats  # noqa: PLC0415
        s = get_collection_stats(vector_store)
        if "error" in s:
            console.print(f"[yellow]Index not found: {s['error']}[/yellow]")
        else:
            console.print(Panel.fit(
                f"Collection: [cyan]{s['collection']}[/cyan]\n"
                f"Rules indexed: [green]{s['count']}[/green]\n"
                f"Location: {s['persist_dir']}",
                title="Knowledge Index Stats",
            ))
    except ImportError:
        console.print("[yellow]chromadb not installed — cannot read stats[/yellow]")


if __name__ == "__main__":
    app()
