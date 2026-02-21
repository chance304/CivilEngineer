"""
CivilEngineer CLI root.

Entry point registered in pyproject.toml as:
    [project.scripts]
    civilengineer = "civilengineer.cli.main:app"
"""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    name="civilengineer",
    help="AI Architectural Copilot — generate professional DXF floor plans.",
    add_completion=False,
)
console = Console()

# Register sub-command groups
from civilengineer.cli.design_commands import design_app  # noqa: E402

app.add_typer(design_app, name="design")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(
            "[bold cyan]CivilEngineer[/bold cyan] — AI Architectural Copilot\n"
            "Run [green]civilengineer --help[/green] to see available commands."
        )


if __name__ == "__main__":
    app()
