#!/usr/bin/env python3
"""Финальная проверка книги: структура, код, ссылки, упражнения/ответы, дубли."""
from __future__ import annotations

import ast
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path("/mnt/data/Book/src")
PDF = Path("/mnt/data/Book/out/DevOps-ot-bita-do-klastera.pdf")
REQ = ["## Типичные ошибки", "## Чек-лист", "## Упражнения"]

files = sorted(SRC.glob("*.md"))
chapters = [f for f in files if f.name.startswith("ch")]
apps = [f for f in files if f.name.startswith("app_")]
issues: list[str] = []

print(f"1. Состав: {len(files)} файлов — {len(chapters)} глав, {len(apps)} приложений")

chars = sum(len(f.read_text(encoding='utf-8')) for f in files)
print(f"2. Объём: {chars} знаков")

# структура
bad_struct = [f.name for f in chapters if any(r not in f.read_text(encoding='utf-8') for r in REQ)]
print(f"3. Обязательные разделы: {'OK' if not bad_struct else bad_struct}")
if bad_struct:
    issues.append(f"неполная структура: {bad_struct}")

# код
langs = Counter()
py_ok = py_bad = 0
errs = []
for f in chapters + apps:
    md = f.read_text(encoding="utf-8")
    for lang, code in re.findall(r"```(\w*)\n(.*?)```", md, re.S):
        langs[lang or "plain"] += 1
        if lang in ("python", "py"):
            try:
                ast.parse(code)
                py_ok += 1
            except SyntaxError:
                py_bad += 1
                errs.append((f.name, code.splitlines()[0][:50] if code.strip() else ""))
print(f"4. Код: {sum(langs.values())} блоков, python {py_ok} ок / {py_bad} фрагментов")
for e in errs:
    print("   фрагмент:", e)

# ссылки
nums = set()
for f in chapters:
    m = re.match(r"ch(\d+)([a-e]?)_", f.name)
    nums.add((int(m.group(1)), m.group(2)))
pat = re.compile(r"(?:глав[аеуы]|гл\.)\s*№?\s*(\d+)([a-e]?)", re.I)
refs = bad = 0
for f in files:
    for m in pat.finditer(f.read_text(encoding="utf-8")):
        refs += 1
        if (int(m.group(1)), m.group(2)) not in nums:
            bad += 1
print(f"5. Ссылки: {refs}, битых {bad}")
if bad:
    issues.append(f"битых ссылок: {bad}")

# упражнения vs ответы
def count_ex(f):
    t = f.read_text(encoding="utf-8")
    m = re.search(r"^## Упражнения\s*$(.*)", t, re.S | re.M)
    if not m:
        return 0
    block = m.group(1)
    nxt = re.search(r"^## ", block, re.M)
    if nxt:
        block = block[:nxt.start()]
    return len(re.findall(r"^\d+\.\s", block, re.M))

total_ex = sum(count_ex(f) for f in chapters)
answers = defaultdict(int)
missing_items = []
for f in apps:
    t = f.read_text(encoding="utf-8")
    for sec in re.split(r"^## ", t, flags=re.M)[1:]:
        head = sec.splitlines()[0]
        m = re.search(r"Глава\s+(\d+[a-e]?)", head)
        if not m:
            continue
        cnt = len(re.findall(r"^\d+\.\s", sec, re.M))
        answers[m.group(1)] += cnt

print(f"6. Упражнения: {total_ex} всего; ответов по номерам глав: {sum(answers.values())}")

# дубли: 3-словные шинглы
def shingles(text, k=3):
    w = re.findall(r"[а-яёa-z]{4,}", text.lower())
    return {" ".join(w[i:i+k]) for i in range(len(w)-k)}

prose = {}
for f in files:
    t = re.sub(r"```.*?```", " ", f.read_text(encoding="utf-8"), flags=re.S)
    prose[f.name] = shingles(t)
pairs = []
names = list(prose)
for i in range(len(names)):
    for j in range(i+1, len(names)):
        a, b = prose[names[i]], prose[names[j]]
        if not a or not b:
            continue
        inter = len(a & b)
        share = 100 * inter / min(len(a), len(b))
        if share >= 3.0:
            pairs.append((names[i], names[j], round(share, 1)))
pairs.sort(key=lambda x: -x[2])
print(f"7. Похожие пары (3-граммы, ≥3% перекрытия): {len(pairs)}")
for p in pairs[:5]:
    print("   ", p)

# PDF
try:
    from pypdf import PdfReader
    r = PdfReader(str(PDF))
    print(f"8. PDF: {len(r.pages)} страниц, закладок {len(r.outline or [])}")
except Exception as e:
    print("8. PDF не прочитан:", e)

print("\nПРОБЛЕМЫ:", issues or "нет")
