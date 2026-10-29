# Приложение D. Ответы и решения — часть 2 (главы 9–20)

Номера ответов совпадают с номерами упражнений в главах. Код исполним целиком, если не помечено «фрагмент».

## Глава 9. HTTP/1.1: запросы, ответы, заголовки

1. `printf 'GET / HTTP/1.1\r\n\r\n' | nc example.com 80` → `400 Bad Request`; два разных `Host` → тоже `400` (часть серверов отдаёт `421`). `Host` обязателен и единственен: по нему выбирается виртуальный хост, а расхождение значений между фронтендом и бэкендом открывает отравление кэша.

2. Тело `1a\r\nThis is the first chunk.\r\n15\r\nAnd the second one.\r\n0\r\n\r\n` делится на блоки: `0x1a` = 26 байт (текст плюс CRLF), `0x15` = 21 байт, затем нулевой блок. Склейка даёт `This is the first chunk.And the second one.` — ровно это печатает `curl -s`, а `curl -s --raw` показывает блоки с размерами.

3. `return 302` отдаёт `Location`, но `curl -L -X POST -d 'a=1'` повторит запрос как `GET` без тела — операция молча не выполнится. `return 308` сохраняет метод: curl повторяет `POST` с `Content-Length: 3` и телом `a=1`. Поэтому перевод http→https и POST-редиректы делают через 308.

4. С переиспользованием один `curl` с сотней URL делает 1 TCP-рукопожатие (+1 TLS) и 100 запросов по одному соединению. Без него (`curl` в цикле, `Connection: close`) — 100 рукопожатий, 100 сокетов в `TIME_WAIT` на 60 с и ≈4 с лишней задержки при RTT 40 мс.

5. Для формата из главы (`$7` — статус, `$5` — путь, `urt=` — десятое поле), проверено:
   ```
   awk '{split($0,u,/urt=/); t=u[2]+0; c[$7]++;
         if ($7>=500) {e[$5]++; s[$5]+=t; n[$5]++}}
        END {for (k in c) print "code", k, c[k];
             for (p in e) printf "5xx %s %d %.3f\n", p, e[p], s[p]/n[p]}' access.log
   ```
   Вывод: `code 502 2`, `code 200 1`, `code 504 1`, `5xx /v1/orders 2 0.007`. 502 с `urt=0.007` — бэкенд отказал мгновенно; 502 с `urt` около `proxy_read_timeout` — обрыв посреди ответа; 504 — таймаут чтения.

## Глава 10. HTTP/2 и HTTP/3: мультиплексирование и QUIC

1. `curl -so /dev/null -w '%{http_version} %{time_starttransfer}\n' --http2 --limit-rate 100k URL` и то же с `--http1.1`. На одиночном запросе разница 5–20 мс, и h2 обычно медленнее: добавляются `SETTINGS`, `WINDOW_UPDATE`, фрейминг. Выигрыш h2 виден на десятках параллельных ресурсов.

2. С `http2 on;` вывод `openssl s_client -alpn h2` содержит `ALPN protocol: h2`, а `curl -w '%{http_version}'` даёт `2`. Без директивы — `ALPN protocol: http/1.1` или `No ALPN negotiated`, версия `1.1`. Директива действует только в `server` с `listen ... ssl`; после правки — `nginx -t` и `reload`.

3. `iptables -I OUTPUT -p udp --dport 443 -j DROP`, затем `curl --http3 -w '%{http_version} %{time_connect}\n' URL`. Не дождавшись ответа на QUIC-пакеты, curl ждёт транспортный таймаут (обычно 2–5 с) и откатывается на TCP: в выводе `2` или `1.1`. `--http3-only` завершится ошибкой без отката.

4. При 2 % потерь h1.1 с шестью соединениями теряет 1/6 пропускной способности на каждую потерю, h2 — все потоки сразу, они в одном TCP. На RTT 50–100 мс h2 медленнее h1.1 на 20–40 % по полной загрузке страницы из 50 ресурсов. Лечится h3/QUIC, где потоки независимы.

## Глава 11. Куки, сессии, кэширование, CDN

1. `curl -i` показывает `Set-Cookie: session_id=...; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=604800`. От XSS защищает `HttpOnly` (значение не читается из JavaScript), от CSRF — `SameSite`: `Strict` и `Lax` не отправляют куку при кросс-сайтовом POST. `Secure`, `Path`, `Domain`, `Max-Age` задают область и срок.

2. Без `Domain` кука host-only: `curl -b 'sid=1' https://api.example.com/` её не отправит, сервер вернёт анонимный ответ. С `Domain=example.com` она уходит на любой поддомен. Плата — куку видит любой поддомен, поэтому для критичных используют префикс `__Host-`, требующий отсутствия `Domain` и `Path=/`.

3. Фрагмент:
   ```
   proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api:10m inactive=60m;
   location /api/public/ {
       proxy_pass http://backend; proxy_cache api; proxy_cache_valid 200 10s;
       add_header X-Cache-Status $upstream_cache_status always;
   }
   ```
   Первый запрос — `MISS`, второй в течение 10 с — `HIT`, после `sleep 11` — `EXPIRED`: nginx перепроверяет объект у бэкенда. Без `always` статус не виден на 304.

4. У `example.com` HTML приходит с `cache-control: max-age=86000` и сильным `etag`; `If-None-Match` даёт `304` без тела — документ кэшируется, но сутки не обновляется. Разумнее `max-age=60, stale-while-revalidate=600` для HTML и годовой `max-age` с хешем в имени для статики.

5. При `SameSite=Strict` переход по внешней ссылке кросс-сайтовый, поэтому куки нет и пользователь видит форму входа, уже имея сессию. `Lax` отправляет куку при навигации GET, но не при кросс-сайтовом POST. Дополнительно в форму кладут CSRF-токен и проверяют `Origin` на небезопасных методах.

## Глава 12. TLS и сертификаты

1. Сравниваем четыре поля: версию и шифр (`New, TLSv1.3, Cipher is ...`), число звеньев в `Certificate chain`, строку `ALPN protocol`. Без флага `-alpn h2` в выводе будет `No ALPN negotiated` у всех трёх сайтов — это незапрошенный ALPN, а не отсутствие h2; с флагом у `cloudflare.com` и `google.com` появляется `h2`. Одно звено в цепочке — промежуточного нет.

2. `location ^~ /.well-known/acme-challenge/ { return 404; }` ломает HTTP-01: `certbot renew --dry-run` печатает `Invalid response from http://example.com/.well-known/acme-challenge/...: 404` и `Type: unauthorized`, код 1. После удаления location и `reload` тот же прогон даёт `all simulated renewals succeeded`.

3. Фрагмент:
   ```
   end=$(openssl s_client -connect "$HOST:443" -servername "$HOST" </dev/null 2>/dev/null \
         | openssl x509 -noout -enddate | cut -d= -f2)
   days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
   echo "tls_cert_days_left{host=\"$HOST\"} $days" > /var/lib/node_exporter/tls.prom
   [ "$days" -lt 21 ] && exit 1
   ```
   Алерт `tls_cert_days_left < 21` с `for: 1h`; при `notAfter` через 20 дней скрипт возвращает 1.

4. Браузер получает `Strict-Transport-Security: max-age=60` и минуту переписывает `http://` на `https://` до отправки запроса — в логах nginx запросов на порт 80 нет. Откат: отдать `max-age=0` по HTTPS и дождаться истечения прежнего срока; в Chrome ещё `chrome://net-internals/#hsts`.

## Глава 13. REST и проектирование API

1. У GitHub: `POST /repos/{o}/{r}/merges` (слияние), `POST /markdown` (операция без ресурса), `PUT /user/starred/{o}/{r}`. REST-альтернативы: `POST /v1/merge-requests` и `POST /v1/renders` с телом. При переходе теряется очевидность «одна ручка — одно действие» и идемпотентность, которую даёт семантика `PUT`.

2. Перенос: `PATCH /v1/tasks/{id}`, тело `{"project_id": 9}`, успех `200`, идемпотентен — повтор даёт то же состояние. Слияние: `POST /v1/tasks/{id}/merge`, тело `{"source_ids": [7, 8]}`, успех `200` и `{"merged": 2}`, неидемпотентно — обязателен `Idempotency-Key`, повтор возвращает сохранённый ответ.

3. Схема и алгоритм:
   ```
   CREATE TABLE idem (key text PRIMARY KEY, body_hash text NOT NULL,
     status smallint, response jsonb);
   INSERT INTO idem(key, body_hash) VALUES ($1,$2) ON CONFLICT (key) DO NOTHING;
   ```
   Ноль вставленных строк → читаем запись: хеш другой → `422`, `status IS NULL` → `409`, иначе отдаём сохранённые код и тело. Уникальный индекс — единственная защита от гонки двух параллельных запросов.

4. `OFFSET 100000` даёт `Limit -> Index Scan ... rows=100050` и 40–80 мс: база читает и выбрасывает 100 тысяч строк. Cursor `WHERE (created_at, id) < ($1,$2) ORDER BY created_at DESC, id DESC LIMIT 50` — `rows=50`, 0,1–0,3 мс, стоимость не зависит от глубины. Плата — нет перехода на страницу N.

5. В OpenAPI 3.1 описываем путь, схему и `components.responses.Problem` с `application/problem+json`. Клиент генерируем `openapi-python-client`: он разбирает `type/title/status/detail` в исключение и ретраит только `429, 502, 503, 504`, не трогая `400/422`.

## Глава 14. Прокси, балансировщики, reverse proxy

1. Цепочка и значения: клиент 30 с → LB idle 60 с → nginx `proxy_connect_timeout 2s`, `proxy_send_timeout 10s`, `proxy_read_timeout 30s` → приложение 10 с → БД `statement_timeout 5s`. Инверсия — когда клиент ждёт 5 с, а приложение считает 30: клиент уходит, nginx пишет 499, работа жжёт пул.

2. При `max_fails=2 fail_timeout=10s` упадут два запроса, дальше узел выведен на 10 с. С `proxy_next_upstream error timeout` пользователи этого не заметят, но два лишних запроса уйдут на живой бэкенд; возврат в пул — пробным запросом после `fail_timeout`.

3. Round robin при смеси 10 мс и 2 с копит длинные запросы на случайных узлах, p99 тянется к худшему узлу. `least_conn` учитывает активные соединения и выравнивает очередь — p99 падает в 1,5–3 раза. На однородных запросах разницы нет, и round robin дешевле.

4. Рабочий конфиг: `set_real_ip_from 10.0.0.0/8; real_ip_header X-Forwarded-For; real_ip_recursive on;`. Запрос с `-H 'X-Forwarded-For: 1.2.3.4'` с внешнего адреса не входит в доверенную сеть, заголовок игнорируется, `$remote_addr` — реальный IP. С `set_real_ip_from 0.0.0.0/0` подстановка проходит.

5. Шаги: включить запись сессий в Redis параллельно с памятью (dual-write), читать сначала из Redis с фолбэком, дождаться нуля промахов, отключить sticky в балансировщике, убрать локальное хранилище. Точки отката — после dual-write и после отключения sticky; TTL сессий перекрывает окно миграции.

## Глава 15. nginx и event loop

1. Замер на 1000 простаивающих сокетах: потоки дают +10 МиБ RSS и +8 ГиБ виртуальной памяти (стек 8 МиБ на поток), asyncio/selectors — рост в пределах сотен КиБ. На 10 000 соединений потоки упираются в лимиты и переключения контекста, а цикл событий добавляет сотни байт на сокет.

2. `worker_connections 8192` при `worker_rlimit_nofile 1024`: в `error.log` `Too many open files`, клиенты получают 500. Починка без правки `nginx.conf` — drop-in юнита: `systemctl edit nginx` с `[Service]` и `LimitNOFILE=65535`, затем `daemon-reload` и `restart`. Проверка — `/proc/<worker>/limits`.

3. При `gzip on` директива `sendfile` неприменима: сжатие требует чтения файла в пользовательское пространство, ядро не может копировать страницы напрямую в сокет. `ab -k -c 100 -n 20000` даёт практически одинаковый RPS для `sendfile on` и `off`, а на несжимаемых типах с `gzip off` разница кратная.

4. Edge-режим (`EPOLLET`) сообщает о готовности один раз; если обработчик прочитал 100 байт из 4096 и не дочитал до `EAGAIN`, второго события не будет и остаток зависнет. Level-режим вернёт дескриптор снова. Вывод: в edge-режиме читать циклом до `EAGAIN`, иначе теряются данные.

5. На 8 ядрах `worker_processes 4` дают максимальный RPS и минимальный p99; `32` — RPS ниже на 10–20 %, p99 выше в разы. `vmstat 1` показывает рост `cs` и `sy`, `pidstat -w` — непроизвольные переключения: воркеры борются за кэш вместо полезной работы.

## Глава 16. Python: окружение

1. После `python3.14 -m venv .venv && .venv/bin/pip install httpx` команда `.venv/bin/python -c 'import sys; print(sys.prefix); print(sys.path[-1])'` даёт `.venv` и `.venv/lib/python3.14/site-packages`; у системного интерпретатора `sys.prefix` — `/usr`, и `httpx` там не импортируется.

2. В `requirements.txt` транзитивные зависимости попадают снимком (`pip freeze`), включая случайные версии dev-инструментов. В `pyproject.toml` — только прямые диапазоны, полный граф с пинами лежит в `uv.lock`: пакетов обычно на 20–40 % меньше, потому что разрешатель выбирает одну версию на граф.

3. Цикл даёт `FOR_ITER`, `STORE_FAST`, `CALL` для `append`, `JUMP_BACKWARD` — генератора нет. В варианте с генераторным выражением видно `LOAD_CONST (<code object <genexpr>>)`, затем `MAKE_FUNCTION`: объект создаётся вызовом этого кода, его тело начинается с `RETURN_GENERATOR` и содержит `YIELD_VALUE`.

4. `python -m build && unzip -l dist/tasks_api-0.3.0-py3-none-any.whl` показывает пакет, `METADATA`, `entry_points.txt`. Типичная находка — нет шаблонов и `py.typed`: запуск из корня находил их через текущую директорию в `sys.path`, а после установки в чистый venv — `FileNotFoundError`.

5. Фрагмент workflow:
   ```
   strategy: {matrix: {python: ["3.13", "3.14"]}, fail-fast: false}
   steps:
     - run: uv lock --check
     - run: uv sync --frozen
     - run: uv run pytest -q
   ```
   `uv lock --check` падает при расхождении `pyproject.toml` и `uv.lock`, `--frozen` запрещает обновлять lock при установке, матрица прогоняет обе ветки.

## Глава 17. Синтаксис и типы: коллекции, срезы, comprehension

1. `set` даёт уникальные сервисы, чтобы comprehension не проходил по дублям:
   ```
   metrics = [{"service": "api", "p95": 120}, {"service": "api", "p95": 300},
              {"service": "web", "p95": 90}]
   out = {s: max(m["p95"] for m in metrics if m["service"] == s)
          for s in {m["service"] for m in metrics}}
   print(out)
   ```
   Вывод `{'api': 300, 'web': 90}`: `max` по фильтру даёт максимум за один проход, без сортировки.

2. Баг: `acc=[]` вычисляется при `def` и живёт в `func.__defaults__`, поэтому вызовы делят список. Исправление без смены сигнатуры:
   ```
   def batch(items, size=10, acc=None):
       acc = [] if acc is None else acc
       acc.append(items)
       return acc
   print(batch("a"), batch("b"))
   ```
   Вывод `['a'] ['b']`; клиенты, передающие `acc` явно, работают как раньше.

3. Аннотации:
   ```
   from typing import Literal
   def render(cfg: dict[str, str | int], mode: Literal["fast", "safe"]) -> tuple[str, int]:
       return str(cfg), 0
   ```
   `mypy --strict` на вызове `render({}, mode="turbo")` печатает `Argument "mode" to "render" has incompatible type "Literal['turbo']"; expected "Literal['fast', 'safe']"` — ошибка ловится до запуска.

4. Замер на 100 000 экземпляров в `set`: с `__slots__` — 13,0 МиБ, без — 16,9 МиБ (≈41 байт на объект). `__eq__` и `__hash__` по паре полей обязательны вместе: определив только `__eq__`, Python обнулит `__hash__`, и объект перестанет попадать в `set`.

5. Проверка `n-1 in coll`, 1000 повторов: 10 элементов — 0,11 мкс список против 0,05 мкс множество; 1 000 — 6,4 мкс против 0,075 мкс (×86); 1 000 000 — 7,2 мс против 0,074 мкс (×97 000). Список перестаёт быть приемлемым на сотнях элементов в цикле: `set` даёт O(1) вместо O(n).

## Глава 18. Функции, замыкания, декораторы

1. `def tag(name, /, *, prefix="app", **attrs)` собирает `prefix:name` и атрибуты; `tag(name="x")` падает с `TypeError: tag() missing 1 required positional argument: 'name'`. Сообщение точное: слэш запрещает передачу по имени, именованный `name` не заполняет позиционный параметр, а `**attrs` его не перехватывает.

2. Фабрика лимитера:
   ```
   import time
   def make_limiter(rate):
       interval, state = 1.0 / rate, {"next": 0.0}
       def allow():
           now = time.monotonic()
           if now >= state["next"]:
               state["next"] = max(now, state["next"]) + interval
               return True
           return False
       return allow
   ```
   Состояние живёт в замыкании, `monotonic` не зависит от перевода часов: `[lim() for _ in range(4)]` → `[True, False, False, False]`.

3. В `retry` добавляем `jitter` и `deadline`: задержка `min(base * factor ** (n-1), max_delay) + random.uniform(0, jitter)`, а перед сном сверяем `time.monotonic() < deadline`; если бюджет исчерпан — `raise last_exc`. При `deadline=0.2` и всегда падающей функции выход за ~0,2 с, а не за все попытки.

4. `@lru_cache` на `load_config(path)` держит результат вечно: правка файла не видна до перезапуска — это и есть устаревшие данные. Инвалидация по `mtime`: ключом сделать `(path, os.stat(path).st_mtime_ns)`, тогда изменение файла создаёт новую запись, а старые вытесняются по `maxsize`.

5. Конвейер `read_lines` → `only_errors` (фильтр по уровню) → `count_by_status` (агрегация в словарь). На файле 20 000 строк пик по `tracemalloc` — 22,8 КиБ, вывод `{'200': 6667, '500': 13333}`. Память постоянна: в ней одна строка и аккумулятор, а не весь файл.

## Глава 19. ООП, dataclasses, протоколы, MRO

1. `@dataclass(frozen=True, slots=True)` с полями `kind`, `name`, `namespace="default"` и свойством `fqn` возвращает `prod/deployment/api`. `frozen=True` генерирует `__hash__`, поэтому `r in {r}` истинно и хеши равны у одинаковых значений; `slots=True` убирает `__dict__`, и опечатка в имени поля падает сразу.

2. Порядок задаётся объявлением базовых классов снизу вверх: `Logs(Metrics)`, `Metrics(Retry)`, `Retry(Timeout)`, `Timeout(Base)`. `Logs.__mro__` = `['Logs', 'Metrics', 'Retry', 'Timeout', 'Base', 'object']`, `handle()` → `['logs', 'metrics', 'retry', 'timeout', 'call']`. Обратный порядок ломает цепочку: `super()` уходит в следующий класс MRO, и слои пропускаются.

3. `Backoff(base, factor, max_delay)` валидирует в сеттерах-свойствах, поэтому проверка срабатывает уже в `__init__`: `Backoff(0.5, 0.5, 3.0)` падает с `ValueError: factor must be >= 1, got 0.5` при создании. Свойство `delays` для `Backoff(0.5, 2.0, 3.0, attempts=5)` даёт `(0.5, 1.0, 2.0, 3.0, 3.0)`.

4. `class Notifier(Protocol): def send(self, text: str) -> bool: ...`; реализации `LogNotifier` и `HttpNotifier` от протокола не наследуются. Функция `def notify(n: Notifier, items: list[str]) -> int` проходит `mypy --strict` с обеими, а класс без `send` даёт `Argument 1 has incompatible type`. `isinstance` проверяет лишь имена методов.

5. Класс на 150 строк с тремя методами без `self` распадается на `@dataclass(frozen=True)` с данными и три свободные функции; фикстур становится меньше, потому что состояние создаётся конструктором (`Config(env="prod")`) вместо `setup_class` и `mocker.patch` атрибутов. Обычно число фикстур падает с 6–8 до 1–2 на модуль.

## Глава 20. Асинхронность: asyncio

1. `fetch_all` оборачивает каждый запрос в `asyncio.timeout(2)` и собирает `(url, ok, elapsed)` через `gather(..., return_exceptions=True)`, чтобы падение одного не рушило остальные. На 20 URL с задержкой 0,2 с последовательный вариант занимает ≈4 с, конкурентный — ≈0,25 с: время равно самому медленному запросу, а не сумме.

2. `asyncio.timeout(5)` вокруг трёх `await` по 2 с: третий отменяется, `TimeoutError` перехватывается, функция возвращает два накопленных результата и `complete=False`. Частичный результат собирают в список по мере готовности, а не после `gather`: при отмене результат `gather` теряется.

3. Семафор берётся внутри задачи, вокруг `async with sem`, счётчик инкрементируется после входа. Для 100 задач по 20 мс при лимите 5: пик 5, гистограмма `[(1, 20), (2, 20), (3, 20), (4, 20), (5, 20)]`, время ≈0,41 с. Семафор вокруг `gather` ограничит создание задач, а не работу.

4. Воркер берёт `async with lock`, меняет метрику и держит её в `try/finally`: `finally` выполняется и при `CancelledError`. После `task.cancel()` через 100 мс проверка даёт `lock.locked() == False`, `inflight == 0`, `task.cancelled() == True`. Глотать `CancelledError` нельзя — задача считается успешной.

5. 10 млн чисел, 4 части по 2,5 млн: один поток — 1,70 с, четыре потока — 2,98 с, четыре процесса — 0,92 с. Потоки медленнее последовательного варианта: GIL не даёт параллелизма, добавляются переключения. Процессы дают ≈1,8× на 8 ядрах; цена — сериализация аргументов и результатов.

---

| Глава | Упражнений | Ответов |
|---|---|---|
| 9. HTTP/1.1 | 5 | 5 |
| 10. HTTP/2 и HTTP/3 | 4 | 4 |
| 11. Куки, сессии, кэш | 5 | 5 |
| 12. TLS и сертификаты | 4 | 4 |
| 13. REST и API | 5 | 5 |
| 14. Прокси и балансировка | 5 | 5 |
| 15. nginx и event loop | 5 | 5 |
| 16. Python: окружение | 5 | 5 |
| 17. Синтаксис и типы | 5 | 5 |
| 18. Функции и декораторы | 5 | 5 |
| 19. ООП и протоколы | 5 | 5 |
| 20. asyncio | 5 | 5 |
| **Итого** | **58** | **58** |
