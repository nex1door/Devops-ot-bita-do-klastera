#!/usr/bin/env python3
"""Проставляет ссылки из глав в глоссарий.

Схема: в глоссарии у каждого термина ставится якорь {{A|gN}}, в главах первое
упоминание термина оборачивается в {{L|gN|Термин}}. build_pdf.py превращает
это в PDF-ссылки (<a href="#gN">) и якоря (<a name="gN"/>).
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path("/mnt/data/Book/src")
GLOSSARY = SRC / "app_c_glossary.md"
MAX_PER_CHAPTER = 6
MIN_TERM_LEN = 5


def load_terms() -> list[tuple[str, str]]:
    """[(id, термин)] в порядке глоссария."""
    text = GLOSSARY.read_text(encoding="utf-8")
    terms = []
    for m in re.finditer(r"^(?:\{\{A\|(g\d+)\}\})?\*\*(.+?)\*\* — ", text, re.M):
        gid = m.group(1)
        if gid:                       # id берём из якоря, а не из позиции:
            terms.append((gid, m.group(2).strip()))   # иначе новые термины сдвинут все ссылки
    return terms


def anchor_glossary(terms: list[tuple[str, str]]) -> int:
    text = GLOSSARY.read_text(encoding="utf-8")
    if "{{A|" in text:
        return 0
    out, count = [], 0
    for line in text.split("\n"):
        m = re.match(r"^\*\*(.+?)\*\* — ", line)
        if m:
            term = m.group(1).strip()
            gid = next((g for g, t in terms if t == term), None)
            if gid:
                line = f"{{{{A|{gid}}}}}{line}"
                count += 1
        out.append(line)
    GLOSSARY.write_text("\n".join(out), encoding="utf-8")
    return count


def strip_code(text: str) -> list[tuple[str, bool]]:
    """Разбивает на строки с флагом «внутри блока кода»."""
    lines, inside = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            inside = not inside
            lines.append((line, True))
            continue
        lines.append((line, inside))
    return lines


TERM_RE_CACHE: dict[str, re.Pattern] = {}


def term_pattern(term: str) -> re.Pattern:
    if term not in TERM_RE_CACHE:
        esc = re.escape(term).replace(r"\ ", r"\s+")
        TERM_RE_CACHE[term] = re.compile(rf"(?<![\w-])({esc})(?![\w-])", re.IGNORECASE)
    return TERM_RE_CACHE[term]


def in_code_span(line: str, pos: int) -> bool:
    """True, если позиция попадает внутрь `инлайн-кода`."""
    return line.count("`", 0, pos) % 2 == 1


def link_chapter(path: Path, terms: list[tuple[str, str]]) -> int:
    text = path.read_text(encoding="utf-8")
    if "{{L|" in text:
        return 0

    lines = strip_code(text)
    linked: set[str] = set()
    count = 0

    # приоритет: длинные термины — они специфичнее
    for gid, term in sorted(terms, key=lambda t: -len(t[1])):
        if count >= MAX_PER_CHAPTER:
            break
        if len(term) < MIN_TERM_LEN or gid in linked:
            continue
        pat = term_pattern(term)
        for i, (line, in_code) in enumerate(lines):
            if in_code or line.startswith("|") or line.startswith("#"):
                continue
            hit = None
            for m in pat.finditer(line):
                if not in_code_span(line, m.start()):
                    hit = m
                    break
            if not hit:
                continue
            found = hit.group(1)
            lines[i] = (line[:hit.start()] + f"{{{{L|{gid}|{found}}}}}" + line[hit.end():], in_code)
            linked.add(gid)
            count += 1
            break

    path.write_text("\n".join(l for l, _ in lines), encoding="utf-8")
    return count


def main() -> None:
    terms = load_terms()
    print(f"терминов в глоссарии: {len(terms)}")
    print(f"якорей добавлено: {anchor_glossary(terms)}")
    total = 0
    for f in sorted(SRC.glob("ch*.md")):
        n = link_chapter(f, terms)
        total += n
        if n:
            print(f"  {f.name}: {n}")
    print(f"всего ссылок: {total}")


if __name__ == "__main__":
    main()
