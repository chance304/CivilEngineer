"""
save_output_node — final pipeline step.

Writes:
  - compliance_report.json to the session output directory
  - Updates project session status to 'completed'
  - Logs a completion summary to state.messages
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from civilengineer.agent.state import AgentState

logger = logging.getLogger(__name__)


def save_output_node(state: AgentState) -> dict:
    """Save report JSON and mark session as complete."""
    session_id    = state.get("session_id", "session")
    output_dir    = state.get("output_dir") or f"output/{session_id}"
    report_dict   = state.get("compliance_report")
    dxf_paths     = state.get("dxf_paths") or []
    errors        = list(state.get("errors", []))
    warnings      = list(state.get("warnings", []))

    out_dir = Path(output_dir)
    report_path: str | None = None

    # Save compliance report JSON
    if report_dict:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            report_file = out_dir / "compliance_report.json"
            report_file.write_text(json.dumps(report_dict, indent=2, default=str))
            report_path = str(report_file)
            logger.info("save_output_node: wrote %s", report_file)
        except Exception as exc:
            warnings.append(f"Could not write compliance report: {exc}")

    # Build completion summary
    compliant = report_dict.get("compliant", False) if report_dict else None
    hard_violations = len(report_dict.get("violations", [])) if report_dict else 0
    soft_warnings   = len(report_dict.get("warnings", [])) if report_dict else 0

    summary_lines = [
        "Design session complete.",
        f"  DXF files: {len(dxf_paths)}",
    ]
    if report_path:
        summary_lines.append(f"  Report: {report_path}")
    if compliant is not None:
        summary_lines.append(
            f"  Compliance: {'PASS ✓' if compliant else 'FAIL ✗'}"
            f"  ({hard_violations} violations, {soft_warnings} warnings)"
        )
    if dxf_paths:
        summary_lines.append("  Output files:")
        for p in dxf_paths:
            summary_lines.append(f"    • {p}")

    summary = "\n".join(summary_lines)
    logger.info(summary)

    # Persist ComplianceReportModel to DB (best-effort; does not block pipeline)
    if report_dict and state.get("project_id") and state.get("session_id"):
        _persist_compliance_to_db(state, report_path)

    return {
        "report_path": report_path,
        "messages": [AIMessage(content=summary)],
        "warnings": warnings,
        "errors": errors,
    }


def _persist_compliance_to_db(state: AgentState, report_path: str | None) -> None:
    """Write ComplianceReportModel to DB via asyncio.run() (best-effort, no crash on failure)."""
    try:
        asyncio.run(_persist_compliance_async(state, report_path))
    except RuntimeError:
        # Event loop already running — the job orchestrator will persist via decision_events
        pass
    except Exception as exc:
        logger.warning("save_output_node: could not persist compliance report to DB: %s", exc)


async def _persist_compliance_async(state: AgentState, report_path: str | None) -> None:
    from civilengineer.db.repositories.decisions_repository import (  # noqa: PLC0415
        write_compliance_report,
    )
    from civilengineer.db.session import AsyncSessionLocal  # noqa: PLC0415

    project = state.get("project") or {}
    async with AsyncSessionLocal() as session:
        await write_compliance_report(
            session,
            project_id=state["project_id"],
            firm_id=project.get("firm_id", ""),
            job_id=project.get("job_id", state.get("session_id", "")),
            session_id=state["session_id"],
            compliance_report=state.get("compliance_report") or {},
            report_path=report_path,
        )
        await session.commit()
