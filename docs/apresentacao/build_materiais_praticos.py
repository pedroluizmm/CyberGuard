"""Regenerate the four PDFs and two PNGs from the presentation sources.

Run: python docs/apresentacao/build_materiais_praticos.py
Requires Chrome or Edge, reportlab and pymupdf. Set CHROME to override the browser.
"""

from html import escape
from pathlib import Path
import os
import re
import subprocess
from tempfile import TemporaryDirectory

import fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate

from build_pdf import browser


HERE = Path(__file__).resolve().parent
DEMOS = HERE / "demos"
REPO = HERE.parents[1]
INK = colors.HexColor("#14293B")
MUTED = colors.HexColor("#42576A")
TEAL = colors.HexColor("#005D56")
DECKS = {
    "opcao_a_fluxo_comparativo": 1,
    "opcao_b_pseudo_animacao": 4,
    "opcao_c_grafo_fluxo": 1,
}
INLINE_MARKDOWN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`")


def inline(text: str) -> str:
    """Render the inline Markdown used by this script's editable source."""
    parts = []
    cursor = 0
    for match in INLINE_MARKDOWN.finditer(text):
        parts.append(escape(text[cursor:match.start()]))
        label, url, bold, code = match.groups()
        if url:
            parts.append(f'<a href="{escape(url)}" color="#005D56"><u>{escape(label)}</u></a>')
        elif bold:
            parts.append(f"<b>{escape(bold)}</b>")
        else:
            parts.append(f'<font color="#005D56">{escape(code)}</font>')
        cursor = match.end()
    parts.append(escape(text[cursor:]))
    return "".join(parts)


def font_family() -> tuple[str, str]:
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    regular = fonts / "segoeui.ttf"
    bold = fonts / "segoeuib.ttf"
    if regular.is_file() and bold.is_file():
        pdfmetrics.registerFont(TTFont("Segoe", regular))
        pdfmetrics.registerFont(TTFont("Segoe Bold", bold))
        pdfmetrics.registerFontFamily("Segoe", normal="Segoe", bold="Segoe Bold")
        return "Segoe", "Segoe Bold"
    return "Helvetica", "Helvetica-Bold"


def draw_guide_page(canvas, document) -> None:
    canvas.setFillColor(TEAL)
    canvas.rect(0, A4[1] - 8, A4[0], 8, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#CFDAE3"))
    canvas.line(document.leftMargin, 35, A4[0] - document.rightMargin, 35)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(document.leftMargin, 22, "CyberGuard  /  Roteiro para demonstração")
    canvas.drawRightString(A4[0] - document.rightMargin, 22, str(document.page))


def build_guide() -> Path:
    source = HERE / "roteiro_pratico_cassandra.md"
    output = source.with_suffix(".pdf")
    normal, bold = font_family()
    body = ParagraphStyle("body", fontName=normal, fontSize=10.8, leading=14.5, textColor=INK, spaceAfter=5)
    title = ParagraphStyle("title", parent=body, fontName=bold, fontSize=25, leading=28, spaceAfter=8)
    subtitle = ParagraphStyle("subtitle", parent=body, fontSize=10.2, textColor=MUTED, spaceAfter=9)
    heading = ParagraphStyle("heading", parent=body, fontName=bold, fontSize=12, leading=15, textColor=TEAL, spaceBefore=5, spaceAfter=2, keepWithNext=True)
    note = ParagraphStyle("note", parent=body, fontSize=9.2, leading=12, backColor=colors.HexColor("#E7F4F0"), borderPadding=(5, 7, 5, 7), spaceBefore=4, spaceAfter=8)
    sources = ParagraphStyle("sources", parent=body, fontSize=8.1, leading=10.2, textColor=MUTED)

    paragraphs = []
    blocks = re.split(r"\n\s*\n", source.read_text(encoding="utf-8").strip())
    for index, block in enumerate(blocks):
        if block.startswith("# "):
            text, style = block[2:], title
        elif block.startswith("## "):
            text, style = block[3:], heading
        elif block.startswith("**Na tela.**"):
            text, style = block, note
        elif block.startswith("**Fontes.**"):
            text, style = block, sources
        else:
            text, style = block, subtitle if index == 1 else body
        if normal == "Helvetica":
            text = text.replace("→", " > ")
        paragraphs.append(Paragraph(inline(text), style))

    document = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=43, rightMargin=43, topMargin=30, bottomMargin=44,
        title=blocks[0].removeprefix("# "), author="CyberGuard · UNIFOR V3",
    )
    document.build(paragraphs, onFirstPage=draw_guide_page, onLaterPages=draw_guide_page)
    return output


def print_deck(executable: str, source: Path, profile: Path) -> Path:
    output = source.with_suffix(".pdf")
    subprocess.run(
        [executable, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
         f"--user-data-dir={profile}", f"--print-to-pdf={output}", source.as_uri()],
        capture_output=True, check=True, timeout=90,
    )
    return output


def verify_pdf(output: Path, expected_pages: int, export_png: bool = False) -> None:
    with fitz.open(output) as document:
        if len(document) != expected_pages or any(len(page.get_text().strip()) < 150 for page in document):
            raise ValueError(f"{output.name}: expected {expected_pages} pages with text, found {len(document)}")
        if export_png:
            document[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(output.with_suffix(".png"))
    print(f"{output.relative_to(REPO)}: {expected_pages} página(s)")


def main() -> None:
    executable = browser()
    verify_pdf(build_guide(), 1)
    temp_root = REPO / "tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="cyberguard-pratico-", dir=temp_root) as temp:
        for name, pages in DECKS.items():
            output = print_deck(executable, DEMOS / f"{name}.html", Path(temp) / name)
            verify_pdf(output, pages, export_png=pages == 1)


if __name__ == "__main__":
    main()
