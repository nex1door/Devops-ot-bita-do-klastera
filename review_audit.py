#!/usr/bin/env python3
"""Аудит книги: структура, код, дубли, ссылки, версии."""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path("/mnt/data/Book/src")
FILES = sorted(SRC.glob("*.md"))

REQ = ["## Типичные ошибки", "## Чек-лист", "## Упражнения"]


def split_blocks(md: str):
    """Возвращает (проза, [(lang, code)])."""
    prose, blocks = [], []
    lines = md.splitlines()
    i = 0
    buf = []
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip()
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            blocks.append((lang, "\n".join(code)))
            continue
        buf.append(line)
        i += 1
    prose = "\n".join(buf)
    return prose, blocks


rows = []
langs = Counter()
code_ok = defaultdict(lambda: [0, 0])
py_fail, json_fail, yaml_fail = [], [], []
all_prose = {}

for f in FILES:
    md = f.read_text(encoding="utf-8")
    prose, blocks = split_blocks(md)
    chars = len(md)
    code_chars = sum(len(c) for _, c in blocks)
    all_prose[f.name] = prose

    for lang, code in blocks:
        key = (lang or "plain").lower()
        langs[key] += 1
        if key in ("python", "py"):
            try:
                ast.parse(code)
                code_ok["python"][0] += 1
            except SyntaxError as e:
                code_ok["python"][1] += 1
                py_fail.append((f.name, str(e)[:80], code.splitlines()[0][:50] if code else ""))
        elif key == "json":
            try:
                json.loads(code)
                code_ok["json"][0] += 1
            except Exception as e:
                code_ok["json"][1] += 1
                json_fail.append((f.name, str(e)[:60]))
        elif key in ("yaml", "yml"):
            if "{{" in code:            # Helm/Jinja-шаблон, а не готовый YAML
                continue
            try:
                import yaml
                list(yaml.safe_load_all(code))
                code_ok["yaml"][0] += 1
            except Exception as e:
                code_ok["yaml"][1] += 1
                yaml_fail.append((f.name, str(e)[:60]))

    rows.append({
        "file": f.name,
        "chars": chars,
        "prose_pct": round(100 * (chars - code_chars) / chars, 1),
        "h2": len(re.findall(r"^## ", md, re.M)),
        "tables": len(re.findall(r"^\|[\s:\-|]+\|$", md, re.M)),
        "blocks": len(blocks),
        "missing": [r.replace("## ", "") for r in REQ if r not in md],
        "exercises": len(re.findall(r"^\d+\.\s", md.split("## Упражнения")[-1], re.M)) if "## Упражнения" in md else 0,
    })

# --- дубли: 6-словные шинглы между главами
def shingles(text: str, k: int = 6):
    words = re.findall(r"[а-яёa-z]{3,}", text.lower())
    return {" ".join(words[i:i + k]) for i in range(len(words) - k)}

dup_pairs = []
sh = {n: shingles(t) for n, t in all_prose.items() if n.startswith(("ch", "app"))}
names = list(sh)
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        a, b = sh[names[i]], sh[names[j]]
        if not a or not b:
            continue
        inter = len(a & b)
        if inter >= 12:
            dup_pairs.append((names[i], names[j], inter, round(100 * inter / min(len(a), len(b)), 1)))
dup_pairs.sort(key=lambda x: -x[3])

# --- ссылки на главы
chapter_nums = set()
for f in FILES:
    m = re.match(r"ch(\d+)([a-e]?)_", f.name)
    if m:
        chapter_nums.add(m.group(1) + m.group(2))
refs = Counter()
bad_refs = Counter()
for f in FILES:
    if not f.name.startswith("ch"):
        continue
    for m in re.finditer(r"гл\.\s*(\d+[a-e]?)", f.read_text(encoding="utf-8")):
        num = m.group(1)
        refs[num] += 1
        if num not in chapter_nums:
            bad_refs[(f.name, num)] += 1

# --- версии
vers = defaultdict(Counter)
for f in FILES:
    t = f.read_text(encoding="utf-8")
    for m in re.finditer(r"Python\s+(3\.\d+)", t):
        vers["python"][m.group(1)] += 1
    for m in re.finditer(r"Go\s+(1\.\d+)", t):
        vers["go"][m.group(1)] += 1
    for m in re.finditer(r"Kubernetes\s+(1\.\d+)", t):
        vers["k8s"][m.group(1)] += 1

print("=== ОБЪЁМ ===")
total = sum(r["chars"] for r in rows)
print(f"файлов {len(rows)}, знаков {total}, глав {sum(1 for r in rows if r['file'].startswith('ch'))}, "
      f"приложений {sum(1 for r in rows if r['file'].startswith('app'))}")

print("\n=== ГЛАВЫ ВНЕ КОРИДОРА 11–16 тыс. знаков ===")
for r in rows:
    if r["file"].startswith("ch") and not (11000 <= r["chars"] <= 16500):
        print(f"  {r['file']}: {r['chars']}")

print("\n=== ПРОПУЩЕННЫЕ ОБЯЗАТЕЛЬНЫЕ РАЗДЕЛЫ ===")
miss = [(r["file"], r["missing"]) for r in rows if r["missing"] and r["file"].startswith("ch")]
print(f"  {len(miss)} глав с неполной структурой" if miss else "  нет")
for m in miss[:10]:
    print("  ", m)

print("\n=== ДОЛЯ ПРОЗЫ (минимум 70%) ===")
low = [(r["file"], r["prose_pct"]) for r in rows if r["file"].startswith("ch") and r["prose_pct"] < 70]
print(f"  {len(low)} глав ниже 70%: {low}" if low else "  все >= 70%")
avg = sum(r["prose_pct"] for r in rows if r["file"].startswith("ch")) / max(1, sum(1 for r in rows if r["file"].startswith("ch")))
print(f"  средняя доля прозы: {avg:.1f}%")

print("\n=== УПРАЖНЕНИЯ ===")
ex = [r["exercises"] for r in rows if r["file"].startswith("ch")]
print(f"  min {min(ex)}, median {sorted(ex)[len(ex)//2]}, max {max(ex)}, всего {sum(ex)}")

print("\n=== ЯЗЫКИ КОДА ===")
for k, v in langs.most_common(12):
    print(f"  {k:12s} {v}")

print("\n=== ПРОВЕРКА КОДА ===")
for k, (ok, bad) in code_ok.items():
    print(f"  {k}: успешно {ok}, ошибок {bad}")
for e in py_fail[:6]:
    print("   PY:", e)
for e in json_fail[:4]:
    print("   JSON:", e)
for e in yaml_fail[:4]:
    print("   YAML:", e)

print("\n=== ДУБЛИ (6-словные шинглы, перекрытие >=12) ===")
print(f"  пар: {len(dup_pairs)}")
for p in dup_pairs[:8]:
    print(f"   {p[0]} ~ {p[1]}: {p[2]} общих шинглов, {p[3]}% от меньшей")

print("\n=== ССЫЛКИ «гл. N» ===")
print(f"  всего ссылок {sum(refs.values())}, на несуществующие главы: {len(bad_refs)}")
for k, v in list(bad_refs.items())[:8]:
    print("   ", k, v)

print("\n=== ВЕРСИИ В ТЕКСТЕ ===")
for k, c in vers.items():
    print(f"  {k}: {dict(c.most_common(6))}")
