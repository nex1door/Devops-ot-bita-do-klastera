# Глава 22. Файлы, конфиги, логирование

Сервис на Python почти всё время говорит не по HTTP, а с локальными сущностями: читает конфиг, пишет состояние, ведёт лог. Именно здесь прячутся самые некрасивые инциденты — обрезанный на полуслове JSON после перезапуска пода, «кракозябры» в отчёте, потому что файл читали в кодировке локали, и токен доступа, попавший в лог и уехавший в общий Elastic. Эта глава о трёх бытовых вещах, которые в проде оказываются критичными: работа с путями и кодировками, атомарная запись и форматы конфигов, и логирование, которое помогает, а не вредит.

## Пути: pathlib вместо строк

Склейка путей через `+` и `os.path.join` работает, но не даёт ни типов, ни проверок. `pathlib` даёт объект `Path`, который умеет нужное без вызовов `os`:

```python
from pathlib import Path

root = Path("/srv/app")
conf = root / "conf" / "app.toml"
report = Path("report.csv")

print(conf)
print(report.suffix, report.stem, report.with_suffix(".json"))
```

```text
/srv/app/conf/app.toml
.csv report report.json
```

Раньше для этого требовался `os.path`: `p.parent`, `p.name`, `p.suffix`, `p.with_suffix(".json")`, `p.exists()`, `p.mkdir(parents=True, exist_ok=True)`. Последняя строка — способ создать дерево каталогов, не проверяя каждый уровень: `parents=True` создаёт цепочку, `exist_ok=True` не падает на существующем каталоге.

`Path` — это `os.PathLike`, его принимают `open`, `shutil`, `subprocess`. Тильду `open` не раскрывает — это делает шелл, поэтому нужен `Path("~/app.conf").expanduser()`. А `.resolve()` приводит путь к абсолютному и раскрывает симлинки: если приложение читает конфиг по относительному пути, а {{L|g115|systemd}} запускает его с другим `WorkingDirectory`, получатся два разных файла. Пути из аргументов командной строки разрешаются сразу, пути по умолчанию строятся от известного каталога, а не от текущего.

## Кодировки и переводы строк

В Python 3.14 `open()` без аргумента `encoding` использует кодировку локали. В контейнере это обычно {{L|g125|UTF-8}}, на старом сервере с `LANG=C` — ASCII или latin-1, и тогда кириллица в имени пользователя ломает запись с `UnicodeEncodeError`. UTF-8 по умолчанию запланирован в следующих ветках (PEP 686), но полагаться на это в 3.14 нельзя.

```python
Path("out.txt").write_text("привет", encoding="utf-8")
```

Правило простое: `encoding="utf-8"` пишется явно в каждом `open`, `read_text`, `write_text`. Найти пропуски помогает запуск с `python -X warn_default_encoding` — он печатает `EncodingWarning` на каждый неявный выбор кодировки.

Второй источник сюрпризов — переводы строк. В текстовом режиме Python делает универсальный перевод: при чтении `\r\n` становится `\n`, при записи `\n` превращается в `os.linesep`. Для обычного текста это удобно, для форматов с собственными правилами — вредно.

```python
from pathlib import Path
p = Path("a.txt")
p.write_text("a\r\nb\r\n", encoding="utf-8", newline="")
print(repr(p.read_bytes()))
print(p.read_text(encoding="utf-8").splitlines())
```

```text
b'a\r\nb\r\n'
['a', 'b']
```

`newline=""` отключает преобразования — это важно для CSV, где модуль `csv` сам управляет разделителями и кавычками. На Windows без него в файле появляется `\r\r\n`, и потребители видят лишние пустые строки.

```python
import csv
with open("t.csv", "w", encoding="utf-8", newline="") as f:
    csv.writer(f).writerows([["host", "note"], ["n1", "a\nb"]])
```

```text
b'host,note\r\nn1,"a\nb"\r\n'
```

Модуль написал `\r\n`, как требует RFC 4180, и закавычил поле с переводом строки внутри.

## Атомарная запись

Запись «в лоб» — `path.write_text(...)` — не атомарна: файл сначала усекается до нуля, потом наполняется. Между этими моментами есть окно, в котором другой процесс (или вы сами после `SIGKILL`) увидит пустой или наполовину записанный файл. Для состояния, которое читается при старте, это означает потерю данных или падение на разборе.

Надёжный приём: писать во временный файл в том же каталоге, сбрасывать на диск и переименовывать. `os.replace` на POSIX атомарен в пределах одной файловой системы — читатель видит либо старую версию целиком, либо новую целиком.

```python
import os, tempfile
from pathlib import Path

def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

target = Path("/tmp/deploy/state.json")
write_atomic(target, b'{"replicas": 3}')
print(target.read_text(encoding="utf-8"), target.stat().st_size)
```

```text
{"replicas": 3} 15
```

Три детали, без которых приём не работает. Временный файл создаётся **в том же каталоге**: `os.replace` через границу файловых систем не атомарен и падает с `EXDEV`. `fsync` вызывается до переименования, иначе после отключения питания на диске будет запись каталога без содержимого. `mkstemp` создаёт файл с правами `0600`, поэтому права группы выставляются явно через `os.chmod` перед заменой. Для критичных данных добавляют ещё `fsync` каталога — он фиксирует саму запись о переименовании.

## Чтение построчно и память

`readlines()` и `read()` загружают файл целиком: для лога на 4 ГБ это 4 ГБ памяти плюс накладные расходы списка строк, и процесс убивает {{L|g78|OOM killer}}.

Итерация по файлу читает по строке:

```python
from pathlib import Path

errors = 0
with Path("/var/log/nginx/access.log").open(encoding="utf-8", errors="replace") as f:
    for line in f:
        if " 500 " in line:
            errors += 1
print(errors)
```

Память ограничена размером самой длинной строки, а не файла. `errors="replace"` спасает от падения на битом байте: без него одна повреждённая строка гигабайтного лога выбрасывает `UnicodeDecodeError` и обнуляет работу. Обратная сторона — испорченные символы молча становятся `�`, поэтому для точных данных лучше `errors="strict"` и явная обработка.

Если строки нужны пачками (например, для `executemany`), читают блоками:

```python
def chunks(path, size=1000):
    batch = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            batch.append(line.rstrip("\n"))
            if len(batch) == size:
                yield batch
                batch = []
    if batch:
        yield batch
```

## Форматы конфигов: JSON, YAML, TOML

| Формат | Комментарии | Типы | В стандартной библиотеке | Когда уместен |
|---|---|---|---|---|
| JSON | нет | строки, числа, bool, null, массивы, объекты | `json` | обмен с API, машинное состояние |
| YAML | да | богаче JSON (якоря, даты) | нет, нужен PyYAML | конфиги Kubernetes, CI |
| TOML | да | даты, числа с разделителями, таблицы | `tomllib` (чтение) | конфиги приложений |

JSON не поддерживает комментарии и требует кавычек в ключах — для конфига, который правит человек, это неудобно. TOML читается стандартной библиотекой с 3.11, но только на чтение: для записи нужен `tomli-w`. YAML гибок, и именно гибкость делает его опасным:

```python
import yaml
cfg = yaml.safe_load(Path("deploy.yaml").read_text(encoding="utf-8"))
```

`yaml.safe_load` обязателен. `yaml.load` с `Loader=yaml.Loader` и `yaml.full_load` умеют конструировать произвольные объекты Python по тегам вида `!!python/object/apply`, то есть конфиг из ненадёжного источника превращается в выполнение кода. `safe_load` поддерживает только базовые типы — этого хватает для конфигурации.

TOML читается так:

```python
import tomllib
cfg = tomllib.loads('[db]\nhost = "10.0.0.5"\nport = 5432\n')
print(cfg, type(cfg["db"]["port"]))
```

```text
{'db': {'host': '10.0.0.5', 'port': 5432}} <class 'int'>
```

Обратите внимание: порт — уже `int`, а не строка. TOML типизирован, и это снимает целый класс ошибок вида `"5432" + 1`.

## Конфиг из окружения с валидацией

Двенадцатифакторное приложение (12-factor) хранит конфигурацию в переменных окружения: один образ работает в dev и prod, различаясь только env. Ключевое слово — **валидация**: конфиг разбирается один раз при старте, и приложение падает сразу, а не через час на первом запросе.

```python
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int = 5432
    workers: int = 4
    debug: bool = False

def get(env, name, default=None, cast=str):
    raw = env.get(name, default)
    if raw is None:
        raise SystemExit(f"config error: {name} is required")
    try:
        return cast(raw)
    except ValueError:
        raise SystemExit(f"config error: {name}={raw!r} is not {cast.__name__}") from None

def load(env=os.environ) -> Settings:
    return Settings(
        db_host=get(env, "DB_HOST"),
        db_port=get(env, "DB_PORT", "5432", int),
        workers=get(env, "WORKERS", "4", int),
        debug=get(env, "DEBUG", "0", lambda s: s.lower() in {"1", "true", "yes"}),
    )

print(load({"DB_HOST": "db.internal", "WORKERS": "16"}))
for bad in ({"DB_PORT": "5432"}, {"DB_HOST": "x", "DB_PORT": "54o2"}):
    try:
        load(bad)
    except SystemExit as exc:
        print("err:", exc)
```

```text
Settings(db_host='db.internal', db_port=5432, workers=16, debug=False)
err: config error: DB_HOST is required
err: config error: DB_PORT='54o2' is not int
```

`frozen=True` не даёт переписать настройку в рантайме, аргумент `env` делает функцию тестируемой без патча процесса. `SystemExit` с понятным сообщением даёт ненулевой код возврата — оркестратор увидит неудачный старт и не пошлёт трафик в неработающий pod. Читать `os.environ` в глубине кода не стоит: зависимость не видна в сигнатурах, тесты требуют глобальных патчей, а забытая переменная всплывает в самом неудачном месте. Секреты в конфиг-файлы тоже не пишутся: файл попадает в образ и в git.

## Логирование

`print` не умеет уровней, не ставит метку времени и не разделяет потоки. `logging` умеет всё это, но требует настройки на старте. Уровни по возрастанию: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Логгер берут по имени модуля — `logging.getLogger(__name__)` — тогда видно, кто сделал запись, а фильтровать можно по префиксу.

```python
import logging, logging.handlers
from pathlib import Path

fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s",
                        "%Y-%m-%dT%H:%M:%S%z")
log = logging.getLogger("deploy")
log.setLevel(logging.INFO)
handler = logging.handlers.RotatingFileHandler(
    Path("/var/log/deploy/app.log"), maxBytes=64_000_000, backupCount=5,
    encoding="utf-8")
handler.setFormatter(fmt)
log.addHandler(handler)
log.info("started workers=%d", 4)
```

```text
2026-10-29T19:48:20+0500 INFO    deploy started workers=4
```

Каталог для файла должен существовать и быть доступен на запись: сам обработчик его не создаёт. Формат `%Y-%m-%dT%H:%M:%S%z` даёт время с часовым поясом — без него логи из разных зон не складываются в общую картину. Аргументы передаются через `%`-подстановку, а не f-строкой: строка форматируется только если запись действительно будет выведена, и `log.debug("%s", huge_object)` не тратит время на `repr` при выключенном DEBUG.

`RotatingFileHandler` режет файл по размеру, сохраняя `backupCount` архивов с суффиксами `.1`, `.2`. Проверим на маленьком лимите:

```python
h = logging.handlers.RotatingFileHandler(d / "app.log", maxBytes=200, backupCount=2)
for i in range(12):
    log.info("deploy step %02d finished ok", i)
print(sorted(p.name for p in d.iterdir()))
```

```text
['app.log', 'app.log.1']
```

Для ротации по времени есть `TimedRotatingFileHandler(when="midnight")`. Важная оговорка: файловая ротация безопасна только когда писатель один. Несколько процессов, пишущих в один файл, ротируют его независимо и теряют записи — в таких случаях логируют в stdout, а ротацией занимается среда (systemd, Docker, сборщик логов).

### JSON-логи

Для машинного разбора текстовый формат неудобен: regex по строке ломается на многострочных сообщениях. JSON-форматтер решает это одной функцией:

```python
import json, logging

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                 "level": record.levelname, "logger": record.name,
                 "msg": record.getMessage()}
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)
```

```text
{"ts": "2026-10-29T19:48:20+0500", "level": "INFO", "logger": "deploy.json", "msg": "deployed payments to eu-west-1"}
```

`ensure_ascii=False` оставляет кириллицу читаемой, а не `\u043f...`. Трейсбек попадает в поле `exc` и не разрывает JSON на несколько строк.

### Что не логировать

Логи уезжают в общий кластер, реплицируются, попадают в бэкапы и доступны гораздо большему числу людей, чем база. Поэтому в лог не пишут:

- пароли, токены, `Authorization`, cookie и ключи API — даже на DEBUG;
- номера карт, CVV, полные паспортные данные;
- персональные данные, которые не нужны для отладки: email, телефон, адрес;
- полные тела запросов и ответов платежных API.

Вместо значения логируют его идентификатор или хвост: `token=…a91f`, `user_id=88123`. Если маскирование нужно системно, ставят фильтр на логгер, который заменяет значения по регулярному выражению — но фильтр это страховка, а не замена дисциплине.

Ещё один нюанс — инъекция в лог: пользовательская строка с `\n` создаёт фальшивую запись, и в логе появляется «успешный вход», которого не было. Значения из внешнего мира экранируют или логируют через `repr`/JSON.

## Типичные ошибки

1. **`open` без `encoding`.** Кодировка берётся из локали, а она различается между машиной разработчика, CI и продом. Файл в UTF-8 читается как latin-1: вместо текста — «кракозябры» или `UnicodeDecodeError` на первом не-ASCII символе.
2. **Запись состояния без атомарности.** `write_text` усекает файл перед записью; перезапуск в этот момент оставляет пустой файл, и сервис стартует с нуля.
3. **`readlines()` на большом файле.** Список строк материализует весь файл в памяти; на гигабайтном логе процесс убивает OOM killer.
4. **`yaml.load` вместо `safe_load`.** Загрузчик конструирует объекты по тегам, и конфиг из репозитория превращается в выполнение произвольного кода.
5. **Чтение env в глубине кода.** Зависимость не видна, тесты патчат `os.environ` глобально, а отсутствие переменной обнаруживается в момент запроса, а не на старте.
6. **Секреты и PII в логах.** Строка попадает в агрегатор, реплицируется и хранится месяцами; удалить её почти невозможно, а доступ к логам шире, чем к базе.
7. **`print` вместо логов в сервисе.** Ни времени, ни уровня, ни имени модуля; при нескольких воркерах строки перемешиваются, фильтровать нечего.

## Чек-лист

- [ ] Во всех вызовах `open`, `read_text`, `write_text` указан `encoding="utf-8"`, для CSV — `newline=""`.
- [ ] Файлы состояния пишутся через временный файл, `fsync` и `os.replace`.
- [ ] Большие файлы читаются итерацией, а не `read()`/`readlines()`.
- [ ] YAML загружается только через `safe_load`.
- [ ] Конфиг валидируется на старте, при ошибке процесс завершается с понятным сообщением.
- [ ] Логи структурированы, содержат время с зоной и имя логгера.
- [ ] В логах нет токенов, паролей, номеров карт и лишних персональных данных.
- [ ] Ротация настроена, и в одном файле не пишет несколько процессов.

## Упражнения

1. Напишите `tail(path, n)`, возвращающую последние `n` строк, не читая файл целиком; проверьте на файле в 1 ГБ.
2. Реализуйте `merge_configs(base, override)` для TOML-словарей с рекурсивным слиянием, где списки заменяются.
3. Добавьте в JSON-логгер фильтр, маскирующий значения ключей `password`, `token`, `authorization` на любой вложенности.
4. Сделайте ротацию по времени с архивированием в gzip и удалением файлов старше 14 дней без сторонних библиотек.

*Ответы и разбор к этим упражнениям — в приложении D, часть 3.*
