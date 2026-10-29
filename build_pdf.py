#!/usr/bin/env python3
"""Сборка книги: markdown-главы -> PDF (reportlab) с оглавлением и нумерацией.

Использование:
    .venv/bin/python build_pdf.py [--font-size 12.5] [--out out/DevOps.pdf]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageBreak, PageTemplate, Paragraph,
    Preformatted, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

SRC = Path("/mnt/data/Book/src")
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

pdfmetrics.registerFont(TTFont("Book", FONT_DIR / "DejaVuSerif.ttf"))
pdfmetrics.registerFont(TTFont("Book-Bold", FONT_DIR / "DejaVuSerif-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Sans", FONT_DIR / "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", FONT_DIR / "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Mono", FONT_DIR / "DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("Book", normal="Book", bold="Book-Bold", italic="Book", boldItalic="Book-Bold")


def esc(text: str) -> str:
    """Экранирование для reportlab-разметки + инлайн-стили markdown.

    Инлайн-код вынимается в плейсхолдеры до применения *курсива* и **жирного**:
    иначе звёздочка внутри `RateLimit-*` ломает вложенность тегов.
    """
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # якоря и ссылки на глоссарий: {{A|g12}} и {{L|g12|термин}}
    anchors: list[str] = []
    links: list[tuple[str, str]] = []

    def stash_anchor(m: re.Match) -> str:
        anchors.append(m.group(1))
        return f"\x01{len(anchors) - 1}\x01"

    def stash_link(m: re.Match) -> str:
        links.append((m.group(1), m.group(2)))
        return f"\x02{len(links) - 1}\x02"

    text = re.sub(r"\{\{A\|([\w-]+)\}\}", stash_anchor, text)
    text = re.sub(r"\{\{L\|([\w-]+)\|([^}]*)\}\}", stash_link, text)

    codes: list[str] = []

    def stash(match: re.Match) -> str:
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", text)

    def restore(match: re.Match) -> str:
        return f'<font face="Mono" size="9.6">{codes[int(match.group(1))]}</font>'

    text = re.sub("\x00(\\d+)\x00", restore, text)

    def restore_anchor(m: re.Match) -> str:
        return f'<a name="{anchors[int(m.group(1))]}"/>'

    def restore_link(m: re.Match) -> str:
        gid, label = links[int(m.group(1))]
        safe = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<a href="#{gid}" color="#1a4e8a">{safe}</a>'

    text = re.sub("\x01(\\d+)\x01", restore_anchor, text)
    text = re.sub("\x02(\\d+)\x02", restore_link, text)
    return text


def is_tabular(text: str) -> bool:
    """Блок выглядит как таблица: минимум две строки с выровненными колонками."""
    lines = [l for l in text.split("\n") if l.strip()]
    return sum(1 for l in lines if re.search(r"\S {3,}\S", l)) >= 2


def fit_code_style(text: str, style: ParagraphStyle, avail_pt: float,
                   min_size: float = 6.4) -> ParagraphStyle:
    """Уменьшает кегль табличного блока, чтобы колонки не разъехались при переносе."""
    longest = max((len(l.expandtabs(4)) for l in text.split("\n")), default=0)
    if not longest or not is_tabular(text):
        return style
    per_char = pdfmetrics.stringWidth("M", style.fontName, 1.0) or 0.6
    need = longest * per_char
    if need * style.fontSize <= avail_pt - 16:
        return style
    new_size = max(min_size, (avail_pt - 16) / need)
    if new_size >= style.fontSize:
        return style
    return ParagraphStyle("code_fit", parent=style, fontSize=new_size,
                          leading=new_size * 1.3)


def wrap_code_block(text: str, style: ParagraphStyle, avail_pt: float) -> str:
    """Переносит слишком длинные строки кода по ширине полосы набора.

    Preformatted не переносит строки — он их обрезает по границе фрейма,
    поэтому длинные команды и вывод нужно резать заранее, сохраняя отступ
    и помечая продолжение строки.
    """
    char_w = pdfmetrics.stringWidth("M", style.fontName, style.fontSize) or 6.0
    width = max(40, int((avail_pt - 16) / char_w))
    out: list[str] = []
    for line in text.split("\n"):
        line = line.expandtabs(4).rstrip("\r")
        if len(line) <= width:
            out.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        pad = " " * min(indent, 12) + "    "
        rest = line
        first = True
        while len(rest) > width:
            cut = width - (0 if first else len(pad))
            window = rest[:cut]
            space = max(window.rfind(" "), window.rfind(","), window.rfind(";"))
            if space > cut * 0.5:
                piece, rest = rest[:space + 1].rstrip(), rest[space + 1:].lstrip()
            else:
                piece, rest = rest[:cut], rest[cut:]
            out.append(piece if first else pad + piece.lstrip())
            first = False
        out.append(rest if first else pad + rest.lstrip())
    return "\n".join(out)


def make_styles(base_size: float) -> dict[str, ParagraphStyle]:
    leading = base_size * 1.5
    styles = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "body", parent=styles["BodyText"], fontName="Book", fontSize=base_size,
            leading=leading, alignment=TA_JUSTIFY, spaceAfter=base_size * 0.55,
            firstLineIndent=0, allowWidows=0, allowOrphans=0,
        ),
        "h1": ParagraphStyle(
            "h1", parent=styles["Heading1"], fontName="Sans-Bold", fontSize=base_size * 1.85,
            leading=base_size * 2.2, spaceBefore=base_size * 0.6, spaceAfter=base_size * 1.1,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "h1notoc": ParagraphStyle(
            "h1notoc", parent=styles["Heading1"], fontName="Sans-Bold", fontSize=base_size * 1.85,
            leading=base_size * 2.2, spaceBefore=base_size * 0.6, spaceAfter=base_size * 1.1,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "h2": ParagraphStyle(
            "h2", parent=styles["Heading2"], fontName="Sans-Bold", fontSize=base_size * 1.28,
            leading=base_size * 1.6, spaceBefore=base_size * 1.1, spaceAfter=base_size * 0.45,
            textColor=colors.HexColor("#222222"),
        ),
        "h3": ParagraphStyle(
            "h3", parent=styles["Heading3"], fontName="Sans-Bold", fontSize=base_size * 1.06,
            leading=base_size * 1.35, spaceBefore=base_size * 0.8, spaceAfter=base_size * 0.3,
            textColor=colors.HexColor("#333333"),
        ),
        "code": ParagraphStyle(
            "code", fontName="Mono", fontSize=base_size * 0.72, leading=base_size * 0.72 * 1.3,
            backColor=colors.HexColor("#f3f3f0"), borderColor=colors.HexColor("#dcdcd4"),
            borderWidth=0.5, borderPadding=(6, 7, 6, 7), leftIndent=2, spaceBefore=4, spaceAfter=8,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=styles["BodyText"], fontName="Book", fontSize=base_size,
            leading=leading, leftIndent=base_size * 1.2, bulletIndent=base_size * 0.35,
            spaceAfter=base_size * 0.28,
        ),
        "check": ParagraphStyle(
            "check", parent=styles["BodyText"], fontName="Book", fontSize=base_size,
            leading=leading, leftIndent=base_size * 2.5, bulletIndent=base_size * 0.1,
            spaceAfter=base_size * 0.3, bulletFontName="Mono",
            bulletFontSize=base_size * 0.9,
        ),
        "quote": ParagraphStyle(
            "quote", parent=styles["BodyText"], fontName="Book", fontSize=base_size * 0.95,
            leading=leading, leftIndent=base_size * 1.4, textColor=colors.HexColor("#444444"),
            spaceAfter=base_size * 0.5,
        ),
        "cell": ParagraphStyle("cell", fontName="Book", fontSize=base_size * 0.82,
                               leading=base_size * 1.1, alignment=TA_LEFT),
        "cellh": ParagraphStyle("cellh", fontName="Sans-Bold", fontSize=base_size * 0.82,
                                leading=base_size * 1.1, alignment=TA_LEFT),
        "toc1": ParagraphStyle("toc1", fontName="Sans", fontSize=base_size * 0.95,
                               leading=base_size * 1.5, leftIndent=0, spaceBefore=2),
        "toc2": ParagraphStyle("toc2", fontName="Book", fontSize=base_size * 0.85,
                               leading=base_size * 1.3, leftIndent=base_size * 1.1),
        "title": ParagraphStyle("title", fontName="Sans-Bold", fontSize=base_size * 2.6,
                                leading=base_size * 3.1, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("subtitle", fontName="Sans", fontSize=base_size * 1.2,
                                   leading=base_size * 1.7, textColor=colors.HexColor("#555555")),
    }


class BookDoc(BaseDocTemplate):
    def __init__(self, path: str, base_size: float, **kw):
        super().__init__(path, pagesize=A4, leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                         topMargin=2.2 * cm, bottomMargin=2.2 * cm, **kw)
        self.base_size = base_size
        self.chapter = ""
        self._bm = 0
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates([
            PageTemplate(id="main", frames=[frame], onPage=self._decorate),
            PageTemplate(id="empty", frames=[frame], onPage=lambda c, d: None),
        ])

    def beforeDocument(self):
        """Сброс колонтитула и счётчика закладок перед каждым проходом multiBuild."""
        self.chapter = ""
        self._bm = 0

    def _decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Sans", 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        if doc.page > 1:
            canvas.drawString(2.5 * cm, A4[1] - 1.35 * cm, (self.chapter[:90] or ""))
            canvas.drawRightString(A4[0] - 2.5 * cm, 1.3 * cm, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            self.chapter = re.sub(r"<[^>]+>", "", flowable.getPlainText())
            self.notify("TOCEntry", (0, self.chapter, self.page))
            # закладка PDF: без неё на 500 страницах нет навигации
            key = f"bm{self._bm}"
            self._bm += 1
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(self.chapter, key, level=0, closed=False)


def parse_markdown(md: str, st: dict) -> list:
    flow: list = []
    lines = md.splitlines()
    i = 0
    para: list[str] = []

    def flush_para():
        nonlocal para
        if para:
            text = " ".join(x.strip() for x in para).strip()
            if text:
                flow.append(Paragraph(esc(text), st["body"]))
            para = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # код
        if stripped.startswith("```"):
            flush_para()
            lang = stripped[3:].strip()
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            if lang:
                flow.append(Paragraph(f'<font face="Mono" size="8" color="#666666">{esc(lang)}</font>',
                                      st["body"]))
            raw = "\n".join(code)
            code_style = fit_code_style(raw, st["code"], 16.6 * cm)
            flow.append(Preformatted(wrap_code_block(raw, code_style, 16.6 * cm), code_style))
            continue

        # заголовки
        if stripped.startswith("# "):
            flush_para()
            title = stripped[2:].strip()
            flow.append(PageBreak())
            flow.append(Paragraph(esc(title), st["h1"]))
            flow.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#cccccc"),
                                   spaceBefore=2, spaceAfter=10))
            i += 1
            continue
        if stripped.startswith("## "):
            flush_para()
            flow.append(Paragraph(esc(stripped[3:].strip()), st["h2"]))
            i += 1
            continue
        if stripped.startswith("### "):
            flush_para()
            flow.append(Paragraph(esc(stripped[4:].strip()), st["h3"]))
            i += 1
            continue

        # таблица
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            flush_para()
            rows = []
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                body.append(cells)
                i += 1
            rows.append([Paragraph(esc(c), st["cellh"]) for c in header])
            for r in body:
                while len(r) < len(header):
                    r.append("")
                rows.append([Paragraph(esc(c), st["cell"]) for c in r[:len(header)]])
            width = 16.6 * cm / max(1, len(header))
            table = Table(rows, colWidths=[width] * len(header), repeatRows=1)
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeea")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            # небольшие таблицы не разрываем между страницами
            flow.append(KeepTogether(table) if len(rows) <= 12 else table)
            flow.append(Spacer(1, 8))
            continue

        # горизонтальная линия
        if stripped in ("---", "***", "___"):
            flush_para()
            flow.append(HRFlowable(width="60%", thickness=0.5, color=colors.HexColor("#dddddd"),
                                   spaceBefore=8, spaceAfter=8, hAlign="CENTER"))
            i += 1
            continue

        # списки
        if re.match(r"^[-*]\s+", stripped):
            flush_para()
            text = re.sub(r"^[-*]\s+", "", stripped)
            box = re.match(r"^\[( |x|X)\]\s+(.*)$", text)
            if box:
                bullet = "[ ]" if box.group(1) == " " else "[x]"
                flow.append(Paragraph(esc(box.group(2)), st["check"], bulletText=bullet))
            else:
                flow.append(Paragraph(esc(text), st["bullet"], bulletText="•"))
            i += 1
            continue
        if re.match(r"^\d+\.\s+", stripped):
            flush_para()
            num, text = stripped.split(". ", 1)
            flow.append(Paragraph(esc(text), st["bullet"], bulletText=f"{num}."))
            i += 1
            continue

        # цитата
        if stripped.startswith("> "):
            flush_para()
            flow.append(Paragraph(esc(stripped[2:]), st["quote"]))
            i += 1
            continue

        if not stripped:
            flush_para()
            i += 1
            continue

        para.append(line)
        i += 1

    flush_para()
    return flow


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font-size", type=float, default=12.5)
    ap.add_argument("--out", default="/mnt/data/Book/out/DevOps-ot-bita-do-klastera.pdf")
    args = ap.parse_args()

    st = make_styles(args.font_size)

    def sort_key(path: Path) -> tuple[int, str]:
        """Порядок сборки: титул → главы → прочее → приложения."""
        name = path.name
        if name.startswith("00_front"):
            return (0, name)
        if name.startswith("ch"):
            return (1, name)
        if name.startswith("app_"):
            return (3, name)
        return (2, name)

    files = sorted(SRC.glob("*.md"), key=sort_key)
    if not files:
        raise SystemExit("нет глав в /mnt/data/Book/src")

    story: list = []
    # титул
    story.append(Spacer(1, 6 * cm))
    story.append(Paragraph("DevOps:<br/>от бита до кластера", st["title"]))
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("Практическое руководство по Computer Science, сетям, Python, Bash и Go",
                           st["subtitle"]))
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("Октябрь 2026", st["subtitle"]))
    story.append(PageBreak())

    # предисловие — до оглавления
    front = SRC / "00_front.md"
    if front.exists():
        story.extend(parse_markdown(front.read_text(encoding="utf-8"), st))
        story.append(PageBreak())

    toc = TableOfContents()
    toc.levelStyles = [st["toc1"]]
    toc.dotsMinLevel = 0      # точечные лидеры и для глав верхнего уровня
    story.append(Paragraph("Оглавление", st["h1notoc"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(toc)

    for path in files:
        if path.name.startswith("00_front"):
            continue
        story.extend(parse_markdown(path.read_text(encoding="utf-8"), st))

    doc = BookDoc(args.out, args.font_size)
    doc.multiBuild(story)

    try:
        from pypdf import PdfReader
        pages = len(PdfReader(args.out).pages)
    except Exception:
        pages = -1
    chars = sum(len(p.read_text(encoding="utf-8")) for p in files)
    print(f"PDF: {args.out}")
    print(f"страниц: {pages}")
    print(f"символов в исходниках: {chars}")
    print(f"файлов в сборке: {len(files)}")


if __name__ == "__main__":
    main()
