"""Local, dependency-light PDF export for Deep Dog Markdown reports."""

from __future__ import annotations

import io
import re
from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MINT = colors.HexColor("#20B97A")
INK = colors.HexColor("#17231D")
MUTED = colors.HexColor("#607068")
PALE = colors.HexColor("#EDF9F3")
LINE = colors.HexColor("#D9E6DF")


def _inline(text: str) -> str:
    """Convert a conservative Markdown subset into ReportLab markup."""
    fragments: list[str] = []

    def stash(markup: str) -> str:
        token = f"\ue000{len(fragments)}\ue001"
        fragments.append(markup)
        return token

    value = text.strip()

    # Protect code spans and Markdown links before adding automatic links.
    # Otherwise the URL matcher can consume generated tags such as </font>.
    value = re.sub(
        r"`([^`]+)`",
        lambda match: stash(f'<font name="Courier">{escape(match.group(1))}</font>'),
        value,
    )
    value = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda match: stash(
            f'<link href="{escape(match.group(2), quote=True)}" color="#13795B">'
            f'<u>{escape(match.group(1))}</u></link>'
        ),
        value,
    )

    def stash_url(match: re.Match[str]) -> str:
        url = match.group(0)
        trailing = ""
        while url and url[-1] in ".,;:!?":
            trailing = url[-1] + trailing
            url = url[:-1]
        markup = (
            f'<link href="{escape(url, quote=True)}" color="#13795B">'
            f'<u>{escape(url)}</u></link>'
        )
        return stash(markup) + trailing

    value = re.sub(r"https?://[^\s<>]+", stash_url, value)
    value = escape(value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", value)
    for index, markup in enumerate(fragments):
        value = value.replace(f"\ue000{index}\ue001", markup)
    return value


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "CoverTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=25, leading=30, textColor=INK, alignment=TA_CENTER,
        spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        "CoverSub", parent=styles["BodyText"], fontSize=11, leading=16,
        textColor=MUTED, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "H1x", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=18, leading=22, textColor=INK, spaceBefore=14, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "H2x", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=14, leading=18, textColor=MINT, spaceBefore=12, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "H3x", parent=styles["Heading3"], fontName="Helvetica-Bold",
        fontSize=11.5, leading=15, textColor=INK, spaceBefore=9, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "Bodyx", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.4, leading=14, textColor=INK, spaceAfter=7,
        allowWidows=0, allowOrphans=0,
    ))
    styles.add(ParagraphStyle(
        "Bulletx", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.4, leading=14, textColor=INK, leftIndent=12,
        firstLineIndent=-9, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "Smallx", parent=styles["BodyText"], fontSize=8, leading=11,
        textColor=MUTED,
    ))
    styles.add(ParagraphStyle(
        "Codex", parent=styles["Code"], fontName="Courier", fontSize=7.8,
        leading=10.5, textColor=INK, backColor=PALE, borderColor=LINE,
        borderWidth=.5, borderPadding=7, spaceAfter=8,
    ))
    return styles


def _table(lines: list[str], body_style: ParagraphStyle) -> Table:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    if len(rows) > 1 and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in rows[1]):
        rows.pop(1)
    width = 174 * mm
    columns = max(len(row) for row in rows)
    normalized = [row + [""] * (columns - len(row)) for row in rows]
    data = []
    for row_index, row in enumerate(normalized):
        if row_index == 0:
            data.append([
                Paragraph(f'<font color="#FFFFFF"><b>{_inline(cell)}</b></font>', body_style)
                for cell in row
            ])
        else:
            data.append([Paragraph(_inline(cell), body_style) for cell in row])
    table = Table(data, colWidths=[width / columns] * columns, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), MINT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), .45, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def report_to_pdf(report: str, prompt: str = "", mascot_path: Path | None = None) -> bytes:
    """Render a Markdown research report to a polished PDF entirely locally."""
    stream = io.BytesIO()
    styles = _styles()
    title_match = re.search(r"^#\s+(.+)$", report, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Deep Dog Research Report"

    def decorate_page(canvas, doc):
        canvas.saveState()
        page = canvas.getPageNumber()
        canvas.setStrokeColor(LINE)
        canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 9 * mm, "DEEP DOG - LOCAL PDF")
        canvas.drawRightString(192 * mm, 9 * mm, f"Pagina {page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        stream, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title=title, author="Deep Dog",
    )
    story = [Spacer(1, 24 * mm)]
    if mascot_path and mascot_path.exists():
        story.extend([Image(str(mascot_path), width=34 * mm, height=34 * mm), Spacer(1, 8 * mm)])
    story.extend([
        Paragraph(_inline(title), styles["CoverTitle"]),
        HRFlowable(width="38%", thickness=2, color=MINT, spaceBefore=4, spaceAfter=13),
    ])
    if prompt:
        story.append(Paragraph(f"<b>Domanda di ricerca</b><br/>{_inline(prompt)}", styles["CoverSub"]))
        story.append(Spacer(1, 10 * mm))
    story.extend([
        Paragraph(datetime.now().strftime("Generato localmente il %d/%m/%Y alle %H:%M"), styles["CoverSub"]),
        Spacer(1, 28 * mm),
        Paragraph("Report prodotto da Deep Dog. Verifica sempre le fonti prima di prendere decisioni importanti.", styles["Smallx"]),
        PageBreak(),
    ])

    lines = report.splitlines()
    index = 0
    paragraph: list[str] = []

    def flush_paragraph():
        if paragraph:
            story.append(Paragraph(_inline(" ".join(paragraph)), styles["Bodyx"]))
            paragraph.clear()

    while index < len(lines):
        raw = lines[index].rstrip()
        stripped = raw.strip()
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            story.append(Paragraph(escape("\n".join(code)).replace("\n", "<br/>"), styles["Codex"]))
            index += 1
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            if level == 1 and heading.group(2).strip() == title:
                index += 1
                continue
            story.append(Paragraph(_inline(heading.group(2)), styles[{1: "H1x", 2: "H2x", 3: "H3x"}[level]]))
            index += 1
            continue
        if "|" in stripped and index + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[index + 1]):
            flush_paragraph()
            table_lines = [raw, lines[index + 1]]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            story.extend([_table(table_lines, styles["Smallx"]), Spacer(1, 4 * mm)])
            continue
        if re.match(r"^[-*+]\s+", stripped):
            flush_paragraph()
            while index < len(lines) and re.match(r"^\s*[-*+]\s+", lines[index]):
                text = re.sub(r"^\s*[-*+]\s+", "", lines[index])
                story.append(Paragraph(
                    f'<font color="#20B97A"><b>-</b></font> {_inline(text)}',
                    styles["Bulletx"],
                ))
                index += 1
            story.append(Spacer(1, 2 * mm))
            continue
        paragraph.append(stripped)
        index += 1
    flush_paragraph()
    doc.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
    return stream.getvalue()
