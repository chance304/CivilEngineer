"""
Design CLI commands.

civilengineer design run     — Run full design pipeline (interactive)
civilengineer design resume  — Resume an interrupted session
civilengineer design auto    — Non-interactive run with inline requirements
civilengineer design history — List past sessions
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import typer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from civilengineer.agent.graph import build_graph
from civilengineer.agent.state import make_initial_state

design_app = typer.Typer(help="Design pipeline commands.")
console = Console()


# ---------------------------------------------------------------------------
# civilengineer design run
# ---------------------------------------------------------------------------

@design_app.command("run")
def run_design(
    project_id: str = typer.Option(..., "--project", "-p", help="Project ID"),
    output_dir: str = typer.Option("output", "--out", "-o", help="Output directory"),
    requirements: str | None = typer.Option(
        None, "--requirements", "-r",
        help="Inline requirements string (skips interactive interview)",
    ),
) -> None:
    """Run the full design pipeline for a project."""
    session_id = str(uuid.uuid4())[:8]
    console.print(f"[bold]Starting design session[/bold] [cyan]{session_id}[/cyan] "
                  f"for project [cyan]{project_id}[/cyan]")

    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": f"{project_id}:{session_id}"}}

    initial = make_initial_state(project_id, session_id)
    initial["output_dir"] = output_dir

    if requirements:
        initial["requirements"] = _parse_inline_requirements(requirements, project_id)

    try:
        _run_graph_loop(graph, initial, config)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# civilengineer design resume
# ---------------------------------------------------------------------------

@design_app.command("resume")
def resume_design(
    thread_id: str = typer.Argument(help="Thread ID from a previous run"),
    response: str | None = typer.Option(
        None, "--response", "-r",
        help="Response to resume with (otherwise prompted interactively)",
    ),
) -> None:
    """Resume an interrupted design session."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    if not response:
        response = typer.prompt("Resume with")

    try:
        _run_graph_loop(graph, Command(resume=response), config)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# civilengineer design auto
# ---------------------------------------------------------------------------

@design_app.command("auto")
def auto_design(
    project_id: str = typer.Option("demo", "--project", "-p"),
    requirements: str = typer.Option(
        "3BHK 2 floors modern",
        "--requirements", "-r",
        help="Requirements string (e.g. '3BHK 2 floors modern vastu')",
    ),
    plot_width: float  = typer.Option(15.0, "--width",  help="Plot width (m)"),
    plot_depth: float  = typer.Option(20.0, "--depth",  help="Plot depth (m)"),
    road_width: float  = typer.Option(7.0,  "--road",   help="Front road width (m)"),
    output_dir: str    = typer.Option("output", "--out", "-o"),
) -> None:
    """
    Non-interactive design run — no interrupts.

    Injects requirements and a stub plot so the pipeline runs end-to-end
    without user prompts. Useful for automated testing and demos.
    """
    session_id = str(uuid.uuid4())[:8]
    console.print(f"[bold]Auto design session[/bold] [cyan]{session_id}[/cyan]")

    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": f"{project_id}:{session_id}"}}

    initial = make_initial_state(project_id, session_id)
    initial["output_dir"] = output_dir
    initial["requirements"] = _parse_inline_requirements(requirements, project_id,
                                                          road_width_m=road_width)
    initial["plot_info"] = _stub_plot_info(plot_width, plot_depth, road_width)

    # Auto-approve human_review (resume automatically)
    _run_graph_loop(graph, initial, config, auto_approve=True)


# ---------------------------------------------------------------------------
# civilengineer design history
# ---------------------------------------------------------------------------

@design_app.command("history")
def design_history(
    output_dir: str = typer.Option("output", "--out", "-o"),
) -> None:
    """List past design sessions (output directories)."""
    out = Path(output_dir)
    if not out.exists():
        console.print("[yellow]No output directory found.[/yellow]")
        return

    sessions = sorted(out.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    table = Table(title="Past Sessions", show_lines=True)
    table.add_column("Session ID", style="cyan")
    table.add_column("Files", justify="right")
    table.add_column("Compliant")

    for session_dir in sessions:
        if not session_dir.is_dir():
            continue
        files = list(session_dir.iterdir())
        report_file = session_dir / "compliance_report.json"
        compliant = "—"
        if report_file.exists():
            try:
                report = json.loads(report_file.read_text())
                compliant = "[green]✓[/green]" if report.get("compliant") else "[red]✗[/red]"
            except Exception:
                pass
        table.add_row(session_dir.name, str(len(files)), compliant)

    console.print(table)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_graph_loop(graph, initial_or_command, config: dict, auto_approve: bool = False) -> None:
    """
    Drive the graph loop, handling interrupts interactively.

    Interrupts are surfaced as GraphInterrupt exceptions (LangGraph ≥ 0.3).
    We catch them, prompt the user, and resume with Command(resume=answer).
    """
    from langgraph.errors import GraphInterrupt  # noqa: PLC0415

    current = initial_or_command
    while True:
        try:
            result = graph.invoke(current, config=config)
            # Pipeline completed
            _print_completion(result)
            return
        except GraphInterrupt as exc:
            interrupt_data = exc.args[0] if exc.args else {}
            interrupt_type = (
                interrupt_data[0].value.get("type", "unknown")
                if interrupt_data and hasattr(interrupt_data[0], "value")
                else "unknown"
            )
            prompt_text = (
                interrupt_data[0].value.get("prompt", "")
                if interrupt_data and hasattr(interrupt_data[0], "value")
                else ""
            )

            if prompt_text:
                console.print(Panel(prompt_text, title=f"[yellow]{interrupt_type}[/yellow]"))

            if auto_approve:
                # Non-interactive: auto-respond
                if interrupt_type == "human_review":
                    answer = "approve"
                else:
                    answer = "3BHK 2 floors modern"
                console.print(f"[dim]Auto-response: {answer}[/dim]")
            else:
                answer = typer.prompt(f"[{interrupt_type}] Your response")

            current = Command(resume=answer)


def _print_completion(result: dict) -> None:
    """Print a completion summary from final state."""
    errors   = result.get("errors", [])
    warnings = result.get("warnings", [])
    dxf      = result.get("dxf_paths", [])
    report   = result.get("compliance_report", {})

    if errors:
        console.print("[red]Pipeline errors:[/red]")
        for e in errors:
            console.print(f"  [red]✗[/red] {e}")
        return

    compliant = report.get("compliant", None) if report else None
    console.print(Panel.fit(
        f"DXF files: {len(dxf)}\n"
        f"Compliance: {'✓ PASS' if compliant else '✗ FAIL' if compliant is False else '—'}\n"
        + ("\n".join(f"  {p}" for p in dxf) if dxf else ""),
        title="[green]Design complete[/green]",
    ))

    if warnings:
        console.print(f"[yellow]{len(warnings)} warning(s)[/yellow]")


def _parse_inline_requirements(
    text: str,
    project_id: str,
    road_width_m: float | None = None,
) -> dict:
    """Parse a free-text requirements string into a DesignRequirements dict."""
    from civilengineer.requirements_interview.questions import (  # noqa: PLC0415
        answers_to_requirements,
        extract_bhk,
        extract_bool,
        extract_num_floors,
        extract_special_rooms,
        extract_style,
    )
    answers = {
        "building_type":  "residential",
        "num_floors":     extract_num_floors(text),
        "bhk_config":     extract_bhk(text),
        "master_bedroom": True,
        "style":          extract_style(text),
        "vastu":          extract_bool(text) if "vastu" in text.lower() else False,
        "special_rooms":  extract_special_rooms(text),
        "notes":          "",
    }
    return answers_to_requirements(answers, project_id, road_width_m=road_width_m)


def _stub_plot_info(width_m: float, depth_m: float, road_width_m: float) -> dict:
    """Create a minimal PlotInfo dict for testing."""
    return {
        "dwg_storage_key": "stub.dxf",
        "polygon": [],
        "area_sqm": width_m * depth_m,
        "width_m": width_m,
        "depth_m": depth_m,
        "is_rectangular": True,
        "north_direction_deg": 0.0,
        "facing": "south",
        "existing_features": [],
        "scale_factor": 1.0,
        "extraction_confidence": 1.0,
        "extraction_notes": [],
        "road_width_m": road_width_m,
    }
