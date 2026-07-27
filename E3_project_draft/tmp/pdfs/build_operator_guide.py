"""Build the printable E3 project operator guide from the root README."""

from __future__ import annotations

import argparse
import html
import logging
import re
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

LOGGER = logging.getLogger(__name__)
INLINE_CODE = re.compile(r"`([^`]+)`")
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
STRONG = re.compile(r"\*\*([^*]+)\*\*")


class OperatorGuideTemplate(BaseDocTemplate):
    """Document template that records headings for the table of contents."""

    def __init__(self, output_path: Path) -> None:
        """Initialise an A4 document with consistent frames and metadata."""

        super().__init__(
            str(output_path),
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=17 * mm,
            title="ARIA plant E3 project operator guide",
            author="Peter Thorpe and collaborators",
            subject="PT_E3_6 end-to-end workflow operation",
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
        )
        self.addPageTemplates(
            [
                PageTemplate(id="normal", frames=[frame], onPage=draw_page),
            ]
        )

    def afterFlowable(self, flowable: object) -> None:
        """Register level-one and level-two headings in the PDF outline."""

        if not isinstance(flowable, Paragraph):
            return
        style_name = flowable.style.name
        if style_name not in {"GuideHeading1", "GuideHeading2"}:
            return
        level = 0 if style_name == "GuideHeading1" else 1
        text = flowable.getPlainText()
        key = f"section-{self.page}-{len(text)}-{abs(hash(text))}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=False)
        self.notify("TOCEntry", (level, text, self.page, key))


def draw_page(canvas: object, document: BaseDocTemplate) -> None:
    """Draw the page footer and a restrained header."""

    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#475569"))
    canvas.drawString(18 * mm, 10.5 * mm, "ARIA plant E3 project - operator guide v0.9.0")
    canvas.drawRightString(
        A4[0] - 18 * mm,
        10.5 * mm,
        f"Page {document.page}",
    )
    if document.page > 1:
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(colors.HexColor("#0F4C5C"))
        canvas.drawString(18 * mm, A4[1] - 11 * mm, "PT_E3_6 reproducible workflow")
    canvas.restoreState()


def build_styles() -> dict[str, ParagraphStyle]:
    """Create the guide's typography and spacing system."""

    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "GuideTitle",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=27,
            leading=32,
            textColor=colors.HexColor("#0F4C5C"),
            alignment=TA_CENTER,
            spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "GuideSubtitle",
            parent=sample["Normal"],
            fontName="Helvetica",
            fontSize=12,
            leading=17,
            textColor=colors.HexColor("#334155"),
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "GuideHeading1",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=colors.HexColor("#0F4C5C"),
            spaceBefore=7.5 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "GuideHeading2",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#1D6475"),
            spaceBefore=4.5 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "GuideHeading3",
            parent=sample["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor("#334155"),
            spaceBefore=3.4 * mm,
            spaceAfter=1.5 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "GuideBody",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12.3,
            textColor=colors.HexColor("#172033"),
            spaceAfter=1.8 * mm,
            splitLongWords=True,
            allowWidows=0,
            allowOrphans=0,
        ),
        "bullet": ParagraphStyle(
            "GuideBullet",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=8.4,
            leading=10.8,
            leftIndent=4 * mm,
            firstLineIndent=0,
            textColor=colors.HexColor("#172033"),
        ),
        "code": ParagraphStyle(
            "GuideCode",
            parent=sample["Code"],
            fontName="Courier",
            fontSize=6.8,
            leading=8.7,
            textColor=colors.HexColor("#0F172A"),
            leftIndent=1.5 * mm,
            rightIndent=1.5 * mm,
            splitLongWords=True,
        ),
        "table_header": ParagraphStyle(
            "GuideTableHeader",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.1,
            leading=8.8,
            textColor=colors.white,
        ),
        "table_body": ParagraphStyle(
            "GuideTableBody",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=6.9,
            leading=8.7,
            textColor=colors.HexColor("#172033"),
            splitLongWords=True,
        ),
        "toc": ParagraphStyle(
            "GuideTOC",
            parent=sample["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            leftIndent=4 * mm,
            firstLineIndent=-4 * mm,
            textColor=colors.HexColor("#1E3A4C"),
        ),
    }


def render_inline(text: str) -> str:
    """Convert the limited inline Markdown used by the guide to ReportLab markup."""

    escaped = html.escape(text, quote=True)
    escaped = MARKDOWN_LINK.sub(
        lambda match: (
            f'<link href="{html.escape(match.group(2), quote=True)}" '
            f'color="#0F6072">{html.escape(match.group(1))}</link>'
        ),
        escaped,
    )
    escaped = STRONG.sub(r"<b>\1</b>", escaped)
    escaped = INLINE_CODE.sub(
        lambda match: f'<font name="Courier" color="#7C2D12">{match.group(1)}</font>',
        escaped,
    )
    return escaped


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Build a normal paragraph from one Markdown paragraph."""

    return Paragraph(render_inline(text), style)


def code_block(lines: list[str], style: ParagraphStyle) -> Table:
    """Render a code block in a shaded, breakable single-cell table."""

    content = "<br/>".join(
        html.escape(line, quote=False).replace(" ", "&#160;") if line else "&#160;"
        for line in lines
    )
    cell = Paragraph(content, style)
    table = Table([[cell]], colWidths=[166 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ]
        )
    )
    return table


def markdown_table(
    lines: list[str],
    styles: dict[str, ParagraphStyle],
) -> Table:
    """Convert a simple pipe-delimited Markdown table to a styled PDF table."""

    rows: list[list[str]] = []
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if index == 1 and all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(cells)
    column_count = max(len(row) for row in rows)
    normalised = [row + [""] * (column_count - len(row)) for row in rows]
    data: list[list[Paragraph]] = []
    for row_index, row in enumerate(normalised):
        style = styles["table_header"] if row_index == 0 else styles["table_body"]
        data.append([Paragraph(render_inline(cell), style) for cell in row])
    widths = [166 * mm / column_count] * column_count
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4C5C")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                    colors.white,
                    colors.HexColor("#F8FAFC"),
                ]),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.3 * mm),
            ]
        )
    )
    return table


def bullet_list(
    items: list[str],
    styles: dict[str, ParagraphStyle],
    ordered: bool,
) -> ListFlowable:
    """Build an ordered or unordered list from consecutive Markdown items."""

    flow_items = [
        ListItem(Paragraph(render_inline(item), styles["bullet"]), leftIndent=3 * mm)
        for item in items
    ]
    return ListFlowable(
        flow_items,
        bulletType="1" if ordered else "bullet",
        start="1",
        leftIndent=7 * mm,
        bulletFontName="Helvetica",
        bulletFontSize=7.5,
        spaceAfter=2 * mm,
    )


def collect_sections(lines: Iterable[str]) -> list[str]:
    """Collect second-level headings for the cover contents list."""

    return [line[3:].strip() for line in lines if line.startswith("## ")]


def parse_markdown(
    source: str,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    """Parse the project's deliberately limited Markdown into flowables."""

    lines = source.splitlines()
    flowables: list[object] = []
    index = 0
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            joined = " ".join(line.strip() for line in paragraph_lines)
            flowables.append(paragraph(joined, styles["body"]))
            paragraph_lines.clear()

    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            flush_paragraph()
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            flowables.extend(
                [
                    code_block(code_lines, styles["code"]),
                    Spacer(1, 2.2 * mm),
                ]
            )
        elif line.startswith("|") and index + 1 < len(lines):
            flush_paragraph()
            table_lines: list[str] = []
            while index < len(lines) and lines[index].startswith("|"):
                table_lines.append(lines[index])
                index += 1
            flowables.extend(
                [
                    markdown_table(table_lines, styles),
                    Spacer(1, 2.5 * mm),
                ]
            )
            continue
        elif re.match(r"^- ", line):
            flush_paragraph()
            items: list[str] = []
            while index < len(lines) and re.match(r"^- ", lines[index]):
                items.append(lines[index][2:].strip())
                index += 1
            flowables.append(bullet_list(items, styles, ordered=False))
            continue
        elif re.match(r"^[0-9]+\. ", line):
            flush_paragraph()
            items = []
            while index < len(lines) and re.match(r"^[0-9]+\. ", lines[index]):
                items.append(re.sub(r"^[0-9]+\. ", "", lines[index]).strip())
                index += 1
            flowables.append(bullet_list(items, styles, ordered=True))
            continue
        elif line.startswith("### "):
            flush_paragraph()
            flowables.append(Paragraph(render_inline(line[4:]), styles["h3"]))
        elif line.startswith("## "):
            flush_paragraph()
            flowables.append(Paragraph(render_inline(line[3:]), styles["h2"]))
        elif line.startswith("# "):
            flush_paragraph()
            flowables.append(Paragraph(render_inline(line[2:]), styles["h1"]))
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph_lines.append(line)
        index += 1
    flush_paragraph()
    return flowables


def build_guide(source_path: Path, output_path: Path) -> None:
    """Build and write the complete operator-guide PDF."""

    if not source_path.is_file():
        raise FileNotFoundError(f"README not found: {source_path}")
    source = source_path.read_text(encoding="utf-8")
    if any(ord(character) > 127 for character in source):
        raise ValueError("The PDF source must contain ASCII characters only.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    sections = collect_sections(source.splitlines())

    story: list[object] = [
        Spacer(1, 35 * mm),
        Paragraph("ARIA plant E3 project", styles["title"]),
        Paragraph(
            "End-to-end workflow and package operator guide",
            styles["subtitle"],
        ),
        Spacer(1, 10 * mm),
        Table(
            [
                ["Release", "0.9.0"],
                ["Date", "25 July 2026"],
                ["Project", "PT_E3_6 / ARIA plant E3"],
                ["Primary entry point", "E3_project_draft/run_e3_pipeline.sh"],
            ],
            colWidths=[43 * mm, 92 * mm],
            hAlign="CENTER",
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E2E8F0")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("LEADING", (0, 0), (-1, -1), 12),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ]
            ),
        ),
        Spacer(1, 10 * mm),
        Paragraph(
            "This guide covers Slurm and non-Slurm operation, configuration, "
            "directory organisation, adding a new dataset, restart controls, "
            "monitoring, outputs and a quick start for every package.",
            styles["subtitle"],
        ),
        PageBreak(),
        Paragraph("Contents", styles["h1"]),
    ]
    contents = TableOfContents()
    contents.levelStyles = [
        styles["toc"],
        ParagraphStyle(
            "GuideTOC2",
            parent=styles["toc"],
            leftIndent=10 * mm,
            fontSize=8,
            textColor=colors.HexColor("#475569"),
        ),
    ]
    story.extend([contents, PageBreak()])

    body_source = "\n".join(source.splitlines()[1:])
    story.extend(parse_markdown(body_source, styles))
    story.extend(
        [
            Spacer(1, 6 * mm),
            KeepTogether(
                [
                    Paragraph("Document control", styles["h2"]),
                    paragraph(
                        "Source: repository-root README.md in release 0.9.0. "
                        "Commands must still be checked against the immutable run "
                        "configuration and the current cluster policy before execution.",
                        styles["body"],
                    ),
                ]
            ),
        ]
    )

    LOGGER.info("Building %s with %d documented sections", output_path, len(sections))
    document = OperatorGuideTemplate(output_path)
    document.multiBuild(story)
    LOGGER.info("Wrote %s", output_path)


def build_parser() -> argparse.ArgumentParser:
    """Build the named command-line interface."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Root README path.")
    parser.add_argument("--output", required=True, type=Path, help="Output PDF path.")
    return parser


def main() -> int:
    """Run the PDF builder."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    arguments = build_parser().parse_args()
    build_guide(arguments.source.resolve(), arguments.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
