# Глава 24. CLI и упаковка

У каждого сервиса рано или поздно появляется свой инструмент командной строки: миграция, чинилка состояния, генератор конфигов, обёртка над API. Сначала это скрипт на тридцать строк, потом в него добавляют флаги, потом его запускают из CI и из чужого терминала, а через полгода выясняется, что он не умеет возвращать нормальный код возврата, печатает данные в stderr и ставится только копированием файла по scp. Эта глава о том, как сделать CLI, который ведёт себя как нормальная утилита: с подкомандами, осмысленными кодами возврата, разделением потоков и установкой через `pip`.

## argparse: стандартная библиотека

`argparse` входит в Python, ничего ставить не нужно, и для большинства внутренних утилит его достаточно: парсер, аргументы, подкоманды, `--help`.

Что даёт `argparse` бесплатно: приведение типов (`type=Path`), проверку обязательных аргументов, `--help`, сообщение об ошибке и код возврата 2 при неверном использовании. Три вещи стоит делать сразу: `prog` (иначе в подсказках будет `__main__.py`), `description` и `required=True` у подкоманд (иначе вызов без команды молча ничего не делает).

Ограничение: `argparse` многословен — на десять параметров уходит сорок строк.

## typer: декларативный подход

`typer` строит CLI из аннотаций типов и использует `click` как движок.

```python
import typer

app = typer.Typer(help="Заявки на места")

@app.command()
def hold(seat: str, owner: str) -> None:
    """Занять место за сотрудником."""
    typer.echo(f"{seat} -> {owner}")
```

Разница в подходе: в `argparse` описывается парсер, в `typer` — функция, а парсер выводится из сигнатуры. `--help` собирается из докстринга, подкоманды — из функций с декоратором.

| Критерий | `argparse` | `typer` |
|---|---|---|
| Зависимости | нет | `typer`, `click` |
| Объём кода | растёт линейно | минимален |
| Подсказки и валидация | вручную | из аннотаций |
| Прогрев импорта | мгновенный | заметен на холодном старте |
| Предсказуемость | максимальная | зависит от версии |

Утилита, которую человек запускает раз в сутки, выигрывает от `typer`. Скрипт, вызываемый сотни раз в минуту, — от `argparse` без лишних зависимостей.

## Подкоманды

Подкоманды — это то, что отличает инструмент от скрипта: `seatctl hold 12A --owner alice` и `seatctl release 12A` с общими флагами наверху. В `argparse` они делаются через `add_subparsers`, и каждый парсер получает свою функцию через `set_defaults(func=...)`:

```python
import argparse
from pathlib import Path

def build_parser():
    p = argparse.ArgumentParser(prog="seatctl")
    p.add_argument("--state", type=Path, default=Path("seats.json"))
    p.add_argument("--version", action="version", version=f"seatctl {__version__}")
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("--dry-run", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="показать заявки")
    sp.set_defaults(func=cmd_list)
    sp = sub.add_parser("hold", help="занять место")
    sp.add_argument("seat")
    sp.add_argument("--owner", required=True)
    sp.set_defaults(func=cmd_hold)
    sp = sub.add_parser("release", help="снять заявку")
    sp.add_argument("seat")
    sp.set_defaults(func=cmd_release)
    return p
```

Диспетчеризация — одна строка `args.func(args)`; точка входа показана в полном листинге ниже.

Общие флаги (`--state`, `-v`, `--dry-run`) объявляются до `add_subparsers` и работают с обеих сторон от имени команды. Диспетчеризация через `args.func`, а не через `if args.cmd == ...`, — новая команда не требует правки диспетчера.

## Коды возврата

Код возврата — единственный машинно-читаемый результат программы. По соглашению Unix:

| Код | Значение |
|---|---|
| 0 | успех |
| 1 | ошибка приложения (общая) |
| 2 | неверное использование: аргументы, флаги |
| 3 | прикладной конфликт: объект занят, не найден |
| 126 | файл есть, но нет права на исполнение |
| 127 | команда не найдена |
| 128+N | процесс убит сигналом N |

Проверим на реальном инструменте:

```bash
seatctl --state /tmp/seats.json hold 12A --owner alice; echo "rc=$?"
seatctl --state /tmp/seats.json hold 12A --owner bob;  echo "rc=$?"
seatctl --state /tmp/seats.json bogus;                  echo "rc=$?"
```

```text
rc=0
seatctl: место 12A уже занято
rc=3
seatctl: error: argument cmd: invalid choice: 'bogus'
rc=2
```

Разница между 2 и 3 принципиальна для автоматизации: 2 означает «вызвали неправильно, чинить надо вызывающему», 3 — «вызвали правильно, но состояние не позволило». Скрипт, который видит 2, должен падать и звать человека; скрипт, который видит 3, может обработать ситуацию сам.

Из `main` код возвращается числом, а не через `sys.exit` в глубине вызовов: тогда функция тестируется как обычная, а выход происходит в одной точке. Отдельный случай — смерть от сигнала: `SIGTERM` (15) даёт оболочке 143, Ctrl-C (`SIGINT`, 2) — 130. Писать эти коды руками не нужно, но в логах CI их приходится отличать от прикладной ошибки.

## stdout и stderr

Правило: **данные — в stdout, диагностика — в stderr**. Тогда `seatctl list | wc -l` считает заявки, а сообщение «место занято» не попадает в счётчик и остаётся на экране.

```python
def cmd_list(args):
    for seat, owner in sorted(load(args.state)["holds"].items()):
        print(f"{seat}\t{owner}")          # данные
    return 0

def cmd_hold(args):
    if args.seat in state["holds"]:
        print(f"seatctl: место {args.seat} уже занято", file=sys.stderr)
        return EXIT_CONFLICT
```

`print` с `file=sys.stderr` — минимальный вариант; в инструменте с логированием то же делается через `logging.StreamHandler(sys.stderr)`. Смешивать нельзя: при перенаправлении в файл данные и шум оказываются в одном потоке, и парсер ломается.

Ещё два нюанса. Буферизация: при выводе в терминал stdout построчный, при выводе в пайп — блочный, поэтому в `tail -f` прогресс появляется рывками; помогает `print(..., flush=True)` или запуск с `python -u`. И закрытый пайп: `seatctl list | head -1` убивает читателя, следующий `print` получает `BrokenPipeError` и трейсбек в stderr. Этот случай обрабатывают явно — перехватывают `BrokenPipeError`, закрывают stdout и выходят с нулём: для `head` это нормальный конец работы.

## --dry-run и --verbose

`--dry-run` — обещание «ничего не изменится». Реализация должна это гарантировать: не «записать, а потом откатить», а не писать вовсе. В коде это одна ветка в начале `save()` (см. листинг ниже): если флаг выставлен, будущее состояние печатается в stderr, и `return` происходит до любого обращения к диску. Откат здесь непригоден — он сам является записью, а падение между записью и откатом оставляет мусор.

Проверка: после `--dry-run` состояние на диске не меняется, а предполагаемое изменение видно на stderr.

```bash
seatctl --state /tmp/seats.json --dry-run hold 14C --owner carol
seatctl --state /tmp/seats.json list
```

```text
{
  "holds": {
    "12A": "alice",
    "14C": "carol"
  }
}
12A	alice
```

`--verbose` принято делать счётным (`action="count"`): `-v` — INFO, `-vv` — DEBUG. Уровень вычисляется из числа повторов: `logging.WARNING - 10 * min(args.verbose, 2)` даёт WARNING, INFO и DEBUG для нуля, одного и двух флагов, а по умолчанию не печатается ничего, кроме предупреждений. Вывод при `-v` выглядит так:

```text
INFO hold 14C -> carol
```

Правило: `-v` не меняет данные в stdout — диагностика идёт в stderr, иначе флаг ломает пайпы.

## Сборка wheel

Упаковка начинается с `pyproject.toml`. Минимальный файл для инструмента из одного модуля:

```toml
[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "seatctl"
version = "1.4.0"
description = "Управление заявками на места"
requires-python = ">=3.12"
dependencies = []

[project.scripts]
seatctl = "seatctl:main"

[tool.setuptools]
py-modules = ["seatctl"]
```

Секция `[project.scripts]` создаёт точку входа ({{L|g34|entry point}}): при установке в `bin/` появляется файл `seatctl`, который вызывает `seatctl.main()` и возвращает его код. Это лучше ручного `#!/usr/bin/env python`: правильный интерпретатор и работа в venv.

Сборщик `build` ставится отдельно (`python -m pip install build`) и работает в изолированном окружении: зависимости из `[build-system]` подтягиваются во временный venv, и локальный setuptools на результат не влияет.

```bash
python -m build --wheel
```

```text
Successfully built seatctl-1.4.0-py3-none-any.whl
```

```bash
python -m venv /tmp/venv-check
/tmp/venv-check/bin/pip install dist/seatctl-1.4.0-py3-none-any.whl
/tmp/venv-check/bin/seatctl --version
```

```text
seatctl 1.4.0
```

`py3-none-any` — тег совместимости: чистый Python, любая платформа. Wheel — zip с метаданными, при установке ничего не собирается, в отличие от `sdist`.

## Версионирование

Версия должна быть в одном месте. Практика: она живёт в `pyproject.toml`, а код читает её через метаданные пакета:

```python
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("seatctl")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"
```

Второй вариант нужен для запуска из исходников без установки: `importlib.metadata` ищет распределённый пакет и без него бросает исключение — падать из-за этого `--version` не должен.

Схема — семантическое версионирование `MAJOR.MINOR.PATCH`: MAJOR — несовместимое изменение интерфейса, MINOR — новая функциональность, PATCH — исправления. Для CLI интерфейс включает и флаги, и формат вывода: удаление флага ломает чужие скрипты не меньше, чем смена API.

## Приватный индекс и установка из git

Внутренние пакеты не публикуются на PyPI. Их кладут в приватный индекс (devpi, Nexus, Artifactory, GitLab Package Registry):

```bash
pip install --index-url https://pip.internal.example/simple/ seatctl==1.4.0
```

Настройку лучше держать в конфиге, а не в каждой команде:

Файл `~/.config/pip/pip.conf`:

```ini
[global]
index-url = https://pip.internal.example/simple/
trusted-host = pip.internal.example
```

`trusted-host` отключает проверку TLS для хоста. Это компромисс: правильнее поставить внутренний CA в системное хранилище, а `trusted-host` держать как временную меру.

Версии в индексе фиксируются точно (`seatctl==1.4.0`), а для критичных зависимостей — ещё и хешем: `--require-hashes` заставляет `pip` сверять контрольные суммы и отказываться от подменённого файла. Это защита от компрометации зеркала, а не от ошибки в пакете.

Установка прямо из git нужна, когда пакет ещё не собран:

```bash
pip install "git+https://git.internal.example/platform/seatctl.git@v1.4.0"
```

Тег или коммит обязателен: `@main` означает, что завтра у коллег будет другая версия того же кода. Для приватных репозиториев pip ходит по SSH — `git+ssh://git@git.internal.example/...` — и берёт ключи из ssh-agent.

## Инструмент целиком

Соберём `seatctl`: три подкоманды, общие флаги, коды возврата, dry-run. Первая часть — работа с состоянием.

```python
"""seatctl — заявки на места: list / hold / release."""
import argparse
import json
import logging
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_CONFLICT = 0, 1, 2, 3
log = logging.getLogger("seatctl")


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"holds": {}}


def save(path: Path, state: dict, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps(state, ensure_ascii=False, indent=2), file=sys.stderr)
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
```

Вторая часть — команды (функция `cmd_list` приведена выше в разделе о потоках) и точка входа.

```python
def cmd_hold(args: argparse.Namespace) -> int:
    state = load(args.state)
    if args.seat in state["holds"]:
        print(f"seatctl: место {args.seat} уже занято", file=sys.stderr)
        return EXIT_CONFLICT
    state["holds"][args.seat] = args.owner
    save(args.state, state, args.dry_run)
    log.info("hold %s -> %s", args.seat, args.owner)
    return EXIT_OK


def cmd_release(args: argparse.Namespace) -> int:
    state = load(args.state)
    if state["holds"].pop(args.seat, None) is None:
        print(f"seatctl: заявки на {args.seat} нет", file=sys.stderr)
        return EXIT_CONFLICT
    save(args.state, state, args.dry_run)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING - 10 * min(args.verbose, 2),
        format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        return args.func(args)
    except OSError as exc:
        log.error("%s", exc)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
```

`build_parser()` собирает описанные выше подкоманды; `__version__` берётся из метаданных пакета — об этом в разделе о версионировании. Обратите внимание на `main(argv=None)`: аргумент позволяет тестировать разбор без подмены `sys.argv`, а `sys.exit(main())` в единственном месте превращает код возврата в результат процесса.

## Типичные ошибки

1. **Данные в stderr или диагностика в stdout.** Механизм: `print` по умолчанию пишет в stdout, и сообщение об ошибке попадает в файл, который парсят. Пайп `seatctl list | jq` падает на строке «место занято».
2. **Всегда возвращать 0.** Исключение перехвачено, но код не выставлен. CI видит успех, деплой продолжается после неудачной миграции.
3. **`sys.exit` в глубине кода.** Функция становится нетестируемой — она убивает процесс теста; обработка ошибок размазывается по слоям.
4. **`--dry-run`, который пишет.** Флаг проверяется после записи или не проверяется в одной из ветвей. Флаг, которому нельзя верить, хуже отсутствующего.
5. **Зависимость от `@main` при установке из git.** Механизм: ветка двигается, у двух машин оказываются разные версии одного пакета, и баг «воспроизводится только у меня» становится нормой.
6. **Версия в трёх местах.** Механизм: `__version__` в коде, версия в `pyproject.toml` и тег в git расходятся. `--version` врёт, а релиз нельзя сопоставить с коммитом.
7. **Относительные пути по умолчанию.** Механизм: `Path("seats.json")` зависит от текущего каталога. При запуске из {{L|g115|systemd}} с другим `WorkingDirectory` инструмент читает не тот файл.

## Чек-лист

- [ ] У программы есть `prog`, `description` и осмысленный `--help`.
- [ ] Подкоманды объявлены с `required=True`, диспетчеризация через `func`.
- [ ] Успех — 0, ошибка приложения — 1, неверное использование — 2, конфликт — отдельный код.
- [ ] Данные идут в stdout, все сообщения и логи — в stderr.
- [ ] `--dry-run` гарантирует отсутствие записи, а не откат.
- [ ] `-v` считается, уровни логов растут, вывод в stdout не меняется.
- [ ] Точка входа объявлена в `[project.scripts]`, wheel собирается и ставится в чистый venv.
- [ ] Версия читается из метаданных пакета, а не дублируется в коде.

## Упражнения

1. Добавьте в `seatctl` команду `status` с флагом `--json`, которая печатает данные в stdout в двух форматах, не меняя коды возврата.
2. Сделайте `--dry-run` для `release` и напишите тест, который проверяет, что файл состояния не изменился ни на байт.
3. Перепишите `seatctl` на `typer`, сохранив коды возврата и разделение потоков, и сравните объём кода.
4. Соберите wheel, установите его в чистый venv и в контейнер `python:3.14-slim`, затем проверьте `seatctl --version` и `seatctl --help` без исходников рядом.
5. Настройте публикацию в приватный индекс через CI: сборка wheel, проверка версии, загрузка и установка из индекса в отдельном job.

*Ответы и разбор к этим упражнениям — в приложении D, часть 3.*
