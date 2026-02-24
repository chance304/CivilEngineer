"""
PDF design package exporter.

Generates a structured PDF using reportlab with:
  Page 1 — Cover sheet  (project name, client, date, jurisdiction)
  Page 2 — Room schedule (table: floor / room / area / dimensions)
  Page 3 — Schematic floor plans (simple box diagrams per floor)
  Page 4 — Compliance summary (violations table)
  Page 5 — Cost estimate (if provided)

All values are in SI units (metres, sqm, INR).

Usage
-----
    from civilengineer.output_layer.pdf_exporter import PDFExporter

    exporter = PDFExporter()
    path = exporter.export(
        building=building_design,
        compliance_report=compliance_dict,    # from verify_node state
        cost_estimate=cost_estimate,          # optional CostEstimate
        output_dir="output/session123",
    )
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from civilengineer.output_layer.cost_estimator import CostEstimate
from civilengineer.schemas.design import BuildingDesign, RoomType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# reportlab page constants
# ---------------------------------------------------------------------------

_PAGE_W  = 595.0   # A4 width  in points (1 pt = 1/72 inch)
_PAGE_H  = 842.0   # A4 height in points
_MARGIN  = 40.0
_COL_W   = _PAGE_W - 2 * _MARGIN


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


class PDFExporter:
    """Generate a design package PDF from BuildingDesign + supporting data."""

    def export(
        self,
        building: BuildingDesign,
        output_dir: str | Path,
        compliance_report: dict | None = None,
        cost_estimate: CostEstimate | None = None,
        project_name: str = "",
        client_name: str = "",
        filename: str = "design_package.pdf",
    ) -> Path:
        """
        Generate the PDF and return its path.

        Args:
            building:          BuildingDesign from geometry engine.
            output_dir:        Directory to write the PDF into.
            compliance_report: Dict from verify_node (or ComplianceReport.dict()).
            cost_estimate:     CostEstimate from CostEstimator (optional).
            project_name:      Project / building name.
            client_name:       Client / owner name.
            filename:          Output filename.
        """
        from reportlab.lib.pagesizes import A4  # noqa: PLC0415
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: PLC0415
        from reportlab.lib.units import mm  # noqa: PLC0415
        from reportlab.platypus import (  # noqa: PLC0415
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename

        styles = getSampleStyleSheet()
        h1 = styles["Heading1"]
        h2 = styles["Heading2"]
        normal = styles["Normal"]
        small  = ParagraphStyle("small", parent=normal, fontSize=8)

        story = []

        # ---- Cover ----
        story.extend(
            self._cover_page(building, project_name, client_name, h1, h2, normal)
        )
        story.append(PageBreak())

        # ---- Room schedule ----
        story.append(Paragraph("Room Schedule", h1))
        story.append(Spacer(1, 6))
        story.extend(self._room_schedule(building, styles))
        story.append(PageBreak())

        # ---- Schematic floor plans ----
        story.append(Paragraph("Schematic Floor Plans", h1))
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                "Note: schematic only — refer to DXF drawings for construction dimensions.",
                small,
            )
        )
        story.append(Spacer(1, 8))
        story.extend(self._schematic_plans(building, styles))
        story.append(PageBreak())

        # ---- Compliance summary ----
        story.append(Paragraph("Compliance Report", h1))
        story.append(Spacer(1, 6))
        story.extend(self._compliance_page(compliance_report, styles))

        # ---- Cost estimate (optional) ----
        if cost_estimate:
            story.append(PageBreak())
            story.append(Paragraph("Cost Estimate", h1))
            story.append(Spacer(1, 6))
            story.extend(self._cost_page(cost_estimate, styles))

        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=_MARGIN * mm / 2.835,
            rightMargin=_MARGIN * mm / 2.835,
            topMargin=_MARGIN * mm / 2.835,
            bottomMargin=_MARGIN * mm / 2.835,
        )
        doc.build(story)

        logger.info("PDF design package saved: %s", path)
        return path

    # ------------------------------------------------------------------ #
    # Page builders
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cover_page(building, project_name, client_name, h1, h2, normal):
        from reportlab.platypus import Paragraph, Spacer  # noqa: PLC0415

        title = project_name or f"Project {building.project_id}"
        today = date.today().isoformat()

        lines = [
            Spacer(1, 80),
            Paragraph(f"<b>{title}</b>", h1),
            Spacer(1, 12),
            Paragraph("AI Architectural Design Package", h2),
            Spacer(1, 30),
            Paragraph(f"Client: {client_name or '—'}", normal),
            Paragraph(f"Project ID: {building.project_id}", normal),
            Paragraph(f"Design ID: {building.design_id}", normal),
            Spacer(1, 12),
            Paragraph(f"Jurisdiction: {building.jurisdiction}", normal),
            Paragraph(
                f"Building: {building.num_floors} floor(s) | "
                f"Plot {building.plot_width:.1f} m × {building.plot_depth:.1f} m",
                normal,
            ),
            Spacer(1, 12),
            Paragraph(f"Generated: {today}", normal),
            Spacer(1, 20),
            Paragraph(
                "<i>This document was generated by the CivilEngineer AI Copilot. "
                "All dimensions subject to engineer verification before construction.</i>",
                normal,
            ),
        ]
        return lines

    @staticmethod
    def _room_schedule(building, styles):
        from reportlab.lib import colors  # noqa: PLC0415
        from reportlab.platypus import Spacer, Table, TableStyle  # noqa: PLC0415

        header = ["Floor", "Room", "Type", "Width (m)", "Depth (m)", "Area (sqm)"]
        data = [header]

        total_area = 0.0
        for fp in sorted(building.floor_plans, key=lambda f: f.floor):
            for room in fp.rooms:
                data.append([
                    str(fp.floor),
                    room.name,
                    room.room_type.value.replace("_", " ").title(),
                    f"{room.bounds.width:.2f}",
                    f"{room.bounds.depth:.2f}",
                    f"{room.bounds.area:.2f}",
                ])
                total_area += room.bounds.area

        data.append(["", "", "TOTAL", "", "", f"{total_area:.2f}"])

        col_widths = [35, 110, 100, 60, 60, 65]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 9),
            ("FONTSIZE",   (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F3F4")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#AEB6BF")),
            ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#95A5A6")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BDC3C7")),
            ("ALIGN", (3, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return [t, Spacer(1, 12)]

    @staticmethod
    def _schematic_plans(building, styles):
        """Draw simple box-diagram floor plans using reportlab Drawing."""

        from reportlab.graphics.shapes import Drawing, Rect, String  # noqa: PLC0415
        from reportlab.platypus import (  # noqa: PLC0415
            Paragraph,
            Spacer,
        )

        items = []
        SCALE = 18.0  # points per metre

        for fp in sorted(building.floor_plans, key=lambda f: f.floor):
            items.append(Paragraph(f"Floor {fp.floor}", styles["Heading2"]))
            items.append(Spacer(1, 4))

            dw = building.plot_width  * SCALE + 20
            dh = building.plot_depth * SCALE + 20
            d = Drawing(dw, dh)

            # Plot boundary
            d.add(Rect(
                10, 10,
                building.plot_width * SCALE, building.plot_depth * SCALE,
                strokeColor=_rl_color("#2C3E50"), fillColor=_rl_color("#ECF0F1"),
                strokeWidth=1.5,
            ))

            # Rooms
            for room in fp.rooms:
                rx = 10 + room.bounds.x * SCALE
                ry = 10 + room.bounds.y * SCALE
                rw = room.bounds.width * SCALE
                rd = room.bounds.depth * SCALE
                fill = _ROOM_FILL.get(room.room_type, "#D5D8DC")
                d.add(Rect(rx, ry, rw, rd,
                           strokeColor=_rl_color("#717D7E"),
                           fillColor=_rl_color(fill),
                           strokeWidth=0.5))
                # Label
                short = _SHORT_NAMES.get(room.room_type, room.room_type.value[:3].upper())
                font_size = max(4, min(7, int(rw * 0.35)))
                d.add(String(
                    rx + rw / 2, ry + rd / 2 - font_size / 2,
                    short,
                    fontSize=font_size,
                    textAnchor="middle",
                    fillColor=_rl_color("#1A252F"),
                ))

            items.append(d)
            items.append(Spacer(1, 16))

        return items

    @staticmethod
    def _compliance_page(compliance_report, styles):
        from reportlab.lib import colors  # noqa: PLC0415
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle  # noqa: PLC0415

        normal = styles["Normal"]
        items = []

        if not compliance_report:
            items.append(Paragraph("No compliance report available.", normal))
            return items

        compliant = compliance_report.get("compliant", None)
        status_text = "PASS ✓" if compliant else ("FAIL ✗" if compliant is False else "—")
        status_color = "#27AE60" if compliant else "#E74C3C"

        items.append(
            Paragraph(
                f'Overall: <font color="{status_color}"><b>{status_text}</b></font>',
                normal,
            )
        )
        items.append(Spacer(1, 8))

        # Violations table
        violations = compliance_report.get("violations", [])
        warnings   = compliance_report.get("warnings", [])
        all_issues = [
            ("HARD", v.get("rule_name", v.get("rule_id", "?")),
             v.get("message", ""), v.get("room_type", "—"))
            for v in violations
        ] + [
            ("SOFT", v.get("rule_name", v.get("rule_id", "?")),
             v.get("message", ""), v.get("room_type", "—"))
            for v in warnings
        ]

        if all_issues:
            header = ["Severity", "Rule", "Message", "Room"]
            data = [header] + [[s, r, m, rt] for s, r, m, rt in all_issues]
            col_widths = [45, 90, 220, 75]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, -1), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FDFEFE")]),
                ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#95A5A6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BDC3C7")),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("WORDWRAP", (2, 1), (2, -1), True),
            ]))
            items.append(t)
        else:
            items.append(Paragraph("No violations found.", normal))

        return items

    @staticmethod
    def _cost_page(cost_estimate: CostEstimate, styles):
        from reportlab.lib import colors  # noqa: PLC0415
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle  # noqa: PLC0415

        normal = styles["Normal"]
        items = []

        items.append(Paragraph(
            f"Material grade: <b>{cost_estimate.material_grade.upper()}</b>   |   "
            f"Total area: <b>{cost_estimate.total_area_sqm:.1f} sqm</b>",
            normal,
        ))
        items.append(Spacer(1, 8))

        # Summary table
        summary = [
            ["Item", "Amount (₹)"],
            ["Structure",    f"{cost_estimate.structure_cost:,.0f}"],
            ["Finishing",    f"{cost_estimate.finish_cost:,.0f}"],
            ["MEP",          f"{cost_estimate.mep_cost:,.0f}"],
            ["Contingency",  f"{cost_estimate.contingency_cost:,.0f}"],
            ["TOTAL",        f"{cost_estimate.total_cost_inr:,.0f}"],
            ["Cost / sqm",   f"{cost_estimate.cost_per_sqm_inr:,.0f}"],
        ]
        t = Table(summary, colWidths=[200, 120])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("FONTNAME",   (0, -2), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -2), (-1, -1), colors.HexColor("#AEB6BF")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -3), [colors.white, colors.HexColor("#F2F3F4")]),
            ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#95A5A6")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BDC3C7")),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]))
        items.append(t)
        items.append(Spacer(1, 10))
        items.append(Paragraph(f"Formatted total: {cost_estimate.formatted_total()}", normal))

        # Room breakdown
        if cost_estimate.type_breakdown:
            items.append(Spacer(1, 12))
            items.append(Paragraph("Cost by Room Type", styles["Heading2"]))
            items.append(Spacer(1, 4))
            breakdown_data = [["Room Type", "Cost (₹)"]] + [
                [rt.replace("_", " ").title(), f"{cost:,.0f}"]
                for rt, cost in sorted(cost_estimate.type_breakdown.items(),
                                       key=lambda kv: -kv[1])
            ]
            bt = Table(breakdown_data, colWidths=[200, 120])
            bt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTSIZE",   (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F3F4")]),
                ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#95A5A6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BDC3C7")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]))
            items.append(bt)

        # Per-room flooring (show only rooms with a finish override applied)
        rooms_with_finish = [r for r in cost_estimate.room_breakdown if r.flooring_used]
        if rooms_with_finish:
            items.append(Spacer(1, 12))
            items.append(Paragraph("Flooring Selections Applied", styles["Heading2"]))
            items.append(Spacer(1, 4))
            finish_data = [["Floor", "Room Type", "Flooring", "Finish Cost (₹)"]] + [
                [
                    str(r.floor),
                    r.room_type.replace("_", " ").title(),
                    r.flooring_used.title(),
                    f"{r.finish_cost:,.0f}",
                ]
                for r in sorted(rooms_with_finish, key=lambda r: (r.floor, r.room_type))
            ]
            ft = Table(finish_data, colWidths=[35, 120, 90, 95])
            ft.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTSIZE",   (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F3F4")]),
                ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#95A5A6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BDC3C7")),
                ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ]))
            items.append(ft)

        # Tier comparison
        if cost_estimate.tier_comparison:
            items.append(Spacer(1, 12))
            items.append(Paragraph("Grade Comparison (same layout)", styles["Heading2"]))
            items.append(Spacer(1, 4))
            grade_labels = {"basic": "Basic", "standard": "Standard", "premium": "Premium"}
            tier_data = [["Grade", "Total Cost (₹)", "Notes"]] + [
                [
                    grade_labels.get(g, g.title()),
                    f"{v:,.0f}",
                    "(selected)" if g == cost_estimate.material_grade else "",
                ]
                for g, v in [
                    ("basic",    cost_estimate.tier_comparison.get("basic", 0)),
                    ("standard", cost_estimate.tier_comparison.get("standard", 0)),
                    ("premium",  cost_estimate.tier_comparison.get("premium", 0)),
                ]
            ]
            tt = Table(tier_data, colWidths=[80, 130, 80])
            tt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F3F4")]),
                ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#95A5A6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BDC3C7")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]))
            items.append(tt)

        return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rl_color(hex_str: str):
    """Convert '#RRGGBB' to a reportlab Color."""
    from reportlab.lib.colors import HexColor  # noqa: PLC0415
    return HexColor(hex_str)


# Room fill colours for schematic plans
_ROOM_FILL: dict[RoomType, str] = {
    RoomType.MASTER_BEDROOM: "#D6EAF8",
    RoomType.BEDROOM:        "#D6EAF8",
    RoomType.LIVING_ROOM:    "#D5F5E3",
    RoomType.DINING_ROOM:    "#FDFEFE",
    RoomType.KITCHEN:        "#FEF9E7",
    RoomType.BATHROOM:       "#EAF2FF",
    RoomType.TOILET:         "#EAF2FF",
    RoomType.STAIRCASE:      "#FDEBD0",
    RoomType.CORRIDOR:       "#F9F9F9",
    RoomType.STORE:          "#EAEDED",
    RoomType.POOJA_ROOM:     "#F9EBEA",
    RoomType.GARAGE:         "#EAECEE",
    RoomType.HOME_OFFICE:    "#F0F3FF",
    RoomType.BALCONY:        "#E8F8F5",
    RoomType.TERRACE:        "#E8F8F5",
}

# Short display labels for schematic plans
_SHORT_NAMES: dict[RoomType, str] = {
    RoomType.MASTER_BEDROOM: "MBR",
    RoomType.BEDROOM:        "BED",
    RoomType.LIVING_ROOM:    "LIV",
    RoomType.DINING_ROOM:    "DIN",
    RoomType.KITCHEN:        "KIT",
    RoomType.BATHROOM:       "BATH",
    RoomType.TOILET:         "WC",
    RoomType.STAIRCASE:      "STAIR",
    RoomType.CORRIDOR:       "CORR",
    RoomType.STORE:          "STR",
    RoomType.POOJA_ROOM:     "POOJA",
    RoomType.GARAGE:         "GAR",
    RoomType.HOME_OFFICE:    "OFC",
    RoomType.BALCONY:        "BAL",
    RoomType.TERRACE:        "TER",
}
