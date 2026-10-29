# Сборка книги

PY := .venv/bin/python
PDF := out/DevOps-ot-bita-do-klastera.pdf
MD := out/DevOps-ot-bita-do-klastera.md

.DEFAULT_GOAL := help
.PHONY: help venv pdf md links check clean dist

help:  ## Показать список целей
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

venv:  ## Создать окружение и поставить зависимости
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q reportlab pypdf pypdfium2 pyyaml

pdf: $(PDF)  ## Собрать PDF

$(PDF): $(wildcard src/*.md) build_pdf.py
	$(PY) build_pdf.py --out $(PDF)

md:  ## Склеить книгу в один markdown
	$(PY) -c "from pathlib import Path; src=Path('src'); \
key=lambda p:(0,p.name) if p.name.startswith('00_front') else (1,p.name) if p.name.startswith('ch') else (3,p.name) if p.name.startswith('app_') else (2,p.name); \
parts=sorted(src.glob('*.md'), key=key); \
Path('$(MD)').write_text('\n\n'.join(p.read_text(encoding='utf-8').strip() for p in parts)+'\n', encoding='utf-8')"

links:  ## Расставить ссылки из глав в глоссарий
	$(PY) link_glossary.py

check:  ## Полная проверка книги
	$(PY) final_check.py
	$(PY) review_audit.py | head -40

dist: pdf md  ## Собрать всё, что нужно для релиза

clean:  ## Убрать артефакты сборки
	rm -rf __pycache__ out/*.png out/tmp_*.pdf
