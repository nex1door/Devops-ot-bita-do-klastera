# Приложение D. Ответы и решения — часть 5 (дополнительные главы)

## Глава 5d. eBPF: наблюдение за ядром без пересборки

1. `sudo bpftrace -e 'tracepoint:syscalls:sys_enter_execve { printf("%-16s pid=%-7d ppid=%-7d %s\n", comm, pid, ppid, str(args->filename)); } interval:s:60 { exit(); }'` — за минуту на рабочем хосте 40–80 строк вида `bash pid=589529 ppid=589501 /usr/bin/docker`. `comm` берётся из `task->comm`: 16 байт, копия basename бинарника, но её переопределяет `prctl(PR_SET_NAME)`, её наследует `fork`, а у скрипта с шебангом там интерпретатор (`python3`, а не `deploy.py`).

2. `sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat /str(args->filename) == "/srv/data/report.csv"/ { @s[tid]=nsecs; } tracepoint:syscalls:sys_exit_openat /@s[tid]/ { @us = hist((nsecs-@s[tid])/1000); delete(@s[tid]); }'`. На тёплом кэше почти всё в бакете `[1]` (2700 из 3200); после `echo 3 > /proc/sys/vm/drop_caches` бакет `[1]` падает до десятков, вырастают `[8,16)`, `[32,64)`, `[128,256)`: путь и inode ищутся на диске, syscall ждёт ввода-вывода.

3. DNS и рукопожатие — две разные точки. DNS: `uprobe:/lib/x86_64-linux-gnu/libc.so.6:getaddrinfo` плюс `uretprobe` на нём, разница по `tid`. Рукопожатие: `tracepoint:sock:inet_sock_set_state` с `newstate==2` (SYN_SENT) и потом `newstate==1` (ESTABLISHED), ключ `args->skaddr`, имя процесса запоминается в первой пробе. Типично 2–40 мс DNS и 30–40 мс рукопожатие при RTT 30 мс; сверка — `curl -w '%{time_namelookup} %{time_connect}'`.

4. Интерактивный `cat` на терминале ждёт человека: гистограмма off-CPU уходит в секунды и минуты, последний бакет `[1024,2048)` и выше — десятки срабатываний. `dd` ждёт диск: узкий пик в 10–50 мс на блок, хвост до сотен миллисекунд при flush. Форма отражает природу ожидания: неограниченное человеческое против ограниченного по времени устройства.

5. `sudo bpftrace -e 'tracepoint:syscalls:sys_enter_execve { @by_parent[comm] = count(); }'` — на входе в `execve` в `comm` ещё старый образ, то есть родитель. Накладные расходы: `perf stat -e cycles,instructions -a -- sleep 30` до и с пробой — при 5 тыс. exec/с +0,4% CPU, при 50 тыс. +9%. Безопасно до ~10 тыс. событий/с на ядро с агрегатом без `printf`; с `printf` — 2–3 тыс. Выше нужен фильтр в ядре или ringbuf.

## Глава 5e. SSH: ключи, конфиг, туннели

1. `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C 'nextdoor@workstation'`, `ssh-copy-id -i ~/.ssh/id_ed25519.pub -p 2222 nextdoor@127.0.0.1`, затем `PasswordAuthentication no`, `sudo sshd -t && sudo systemctl reload ssh`. С неверным ключом `ssh -vv` печатает `Offering public key: id_other ED25519 SHA256:...`, строки `Server accepts key` нет, сервер отвечает `Authentications that can continue: publickey`, итог — `Permission denied (publickey)`. Пароль выключен, других методов не осталось.

2. Блоки `Host staging` / `Host prod` с разными `IdentityFile` и `IdentitiesOnly yes`. Проверка: `ssh -G staging | grep -i identityfile` → `identityfile ~/.ssh/id_staging`, для `prod` — свой. `IdentitiesOnly` важен: без него агент предлагает все ключи подряд, сервер считает неудачные попытки и после `MaxAuthTries` (6 по умолчанию, в нашем конфиге 3) рвёт соединение с `Too many authentication failures`, хотя нужный ключ у него есть.

3. `ssh -f -N -p 2222 -L 19080:127.0.0.1:8080 nextdoor@127.0.0.1`; `ss -tlnp | grep 19080` → `users:(("ssh",pid=595634,fd=5))`, `curl` → `200`. Слушает клиентский `ssh`: он держит локальный сокет, а TCP к `127.0.0.1:8080` открывает уже удалённая сторона в своём namespace. Сервер о существовании порта 19080 не знает — он есть только на вашей машине.

4. `command="/usr/bin/head -c 4096 /srv/reports/daily.csv",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... ci@build`. `ssh host 'cat /etc/passwd'` печатает первые 4 КиБ отчёта, `ssh -tt host` → `PTY allocation request failed on channel 0`. Ограничения проверяет сервер: `command=` подменяет запрошенное, `no-pty` отклоняет `pty-req`, поэтому обойти их клиентом нельзя.

5. `ControlMaster auto`, `ControlPath ~/.ssh/cm/%r@%h:%p`, `ControlPersist 10m`: первая команда 106 мс, вторая и третья 8–10 мс против 91/92/98 без мультиплексирования. `ProxyJump bastion` даёт два TCP-соединения в цепочке (клиент→бастион и бастион→цель), два KEX и две аутентификации; бастион видит только шифрованный поток, а ключ предъявляется целевой машине.

## Глава 12a. API: что это такое и как им пользоваться

1. Пример на GitHub REST: `Authorization: Bearer <token>`; лимит 5000 запросов в час на токен (60 без токена), заголовки `X-RateLimit-Remaining` и `Reset`; ошибка — `application/json` с `message`, `status`, `documentation_url`; пагинация `per_page`/`page` плюс `Link: rel="next"`; версия — заголовок `X-GitHub-Api-Version: 2022-11-28`; deprecation — `Deprecation` и `Sunset` в ответе и раздел changelog. Критерий: шесть пунктов выписаны из документации, а не угаданы.

2. `curl -i` печатает статусную строку, все заголовки как есть (включая повторы `Set-Cookie`) и тело первого ответа, без перехода по редиректам. httpx редиректы по умолчанию выполняет, отдаёт разобранные заголовки без учёта регистра, склеивает одноимённые через запятую и не показывает статусную строку; `raise_for_status()` бросает `HTTPStatusError` с `.response` внутри, поэтому `Retry-After` и тело ошибки доступны после исключения.

3. Девять записей A…I, страница по три. Offset: `page=1` → A,B,C; `page=2` → D,E,F; вставка N в начало; `page=3&offset=6` → F,G,H — F пришёл дважды, I потерян. Cursor: `?after=<id F>` → G,H,I, потому что условие `(created_at, id) < (:ts, :id)` идёт по индексу и вставка в начало его не сдвигает. Плата за курсор — нельзя прыгнуть на страницу 7.

4. Подпись — `HMAC-SHA256(secret, f"{ts}." + raw_body)`, сравнение через `hmac.compare_digest`, окно `abs(time.time() - int(ts)) <= 300`. Изменённое тело: HMAC не сходится, `401`, событие не сохранено. Подпись недельной давности: HMAC верный, но разница 604 800 с > 300, отказ `401` — окно и есть защита от реплея.

5. Ночная процедура: в Vault лежат `stripe_key` и `stripe_key_next`, приложение читает `_next` при наличии; выкатка; проверка по метрике успешных вызовов; отзыв старого ключа в панели; запись в аудит. При утечке — сначала отзыв, потом замена: `vault kv get -field=stripe_key`, `revoke`, новый ключ, рестарт подов, `gitleaks detect --source .` по истории.

## Глава 24a. Makefile: контракт репозитория

1. Файловая цель с зависимостями от исходников: `BIN:=bin/tasksvc`, `SRC:=$(shell find . -name '*.go' -not -path './vendor/*')`, правило `$(BIN): $(SRC) go.mod` с `go build -trimpath -o $@ ./cmd/tasksvc`, `build: $(BIN)`, `test:`, `clean:`, всё в `.PHONY` кроме `$(BIN)`. Повторный `make build` → `make: 'bin/tasksvc' is up to date.`; `touch cmd/tasksvc/main.go` → пересборка. Работает за счёт сравнения mtime.

2. Пробелы: `Makefile:4: *** missing separator.  Stop.`, код 2. Без `.PHONY` при существующем каталоге: `mkdir test; make test` → `make: 'test' is up to date.`, код 0 — тесты не запускаются, CI зелёный. `NOW = $(shell sleep 1; date +%s)` в одном рецепте дважды даёт 1793000001 и 1793000002: ошибки нет, есть молчаливо разные значения в одной сборке.

3. `PROTOS := $(wildcard proto/*.proto)`, `GEN := $(PROTOS:.proto=.pb.go)`, правило `%.pb.go: %.proto` с `protoc ... $<`, цель `gen: $(GEN)`. Новый `proto/refund.proto` попадает в `wildcard` при следующем запуске, и `make gen` собирает только его — остальные `.pb.go` новее своих `.proto`. Правка Makefile не нужна, `%` покрывает семейство.

4. Две цели пишут в `coverage.out`: при `make -j8` второй процесс открывает файл на запись, первый получает обрезанный профиль, `go tool cover -func` показывает часть пакетов, иногда `open coverage.out: no such file`. Разносим артефакты (`coverage.api.out`, `coverage.db.out`, слияние отдельной целью) или ставим явную зависимость и `.NOTPARALLEL: test`; гонка видна по нестабильному числу покрытия.

5. `deploy:` с `ifdef CONFIRM` и проверкой `ifeq ($(ENV),prod)`; без переменных печатает `plans: kubectl -n prod set image ...` и выходит с нулём, с `ENV=prod CONFIRM=yes` выполняет. Защита в Makefile, потому что `make deploy` — единственная точка входа для человека и CI: скрипт можно вызвать в обход, а цель без `CONFIRM` не выполнится ни у кого.

## Глава 34a. Очереди и асинхронная обработка

1. Очередь объявляется с `x-max-length=100` и `x-max-length-behavior=reject-publish`; публикуем 1000. В очереди остаётся 100, новые не вытесняют старые. С publisher confirms producer получает 100 `ack` и 900 `basic.nack` — это и есть сигнал притормозить. Без confirms publish выглядит успешным, сообщения молча теряются: `rabbitmqctl list_queues name messages_ready` показывает 100 при отправленных 1000.

2. Убиваем процесс после `COMMIT`, до `Ack`: брокер вернёт сообщение с `redelivered=true`. CTE `INSERT INTO processed_events ... ON CONFLICT DO NOTHING RETURNING 1` не вернёт строк, вставка в `payments` не выполнится, обработчик завершится успешно. В таблице одна строка на ключ, баланс 1000, а не 2000: дедуп и запись — одна транзакция.

3. Три retry-очереди без потребителей с `x-message-ttl` 5000/30000/300000 и DLX обратно в рабочую; счётчик попыток — в заголовке `x-attempts`, после третьей `nack(requeue=false)` → DLQ. `x-death` растёт: `[{count:1,reason:expired,queue:payments.retry.5s}]`, затем `count:2` с `retry.30s`, затем `count:3` и сообщение в `payments.dlq`. Монотонный `count` — доказательство, что задержка реально применялась.

4. `kafka-topics.sh --create --partitions 3 --replication-factor 3`: ключ `order_id` даёт `hash(key) % 3`, и `created → paid → shipped` одного заказа идут в одну партицию по порядку. Горячий ключ виден в `--describe --group payments-worker`: одна партиция с LAG в тысячи, две по нулю — порядок сохранён, но параллелизм на этом ключе потерян.

5. `time.Sleep(200 * time.Millisecond)` в обработчике даёт 5 сообщений/с на потребителя при входе 50/с: лаг растёт на 45/с, за 10 минут — 27 000. Порог алерта считаем по времени: `lag / rate > SLO/2`, то есть при SLO 60 с сигнал на 30 с лага (150 сообщений), а не на «10 000», которое на здоровой системе срабатывает ложно.

## Глава 34b. SQL: индексы, планы, блокировки

1. Миллион заказов, `status` с четырьмя значениями. Без индекса: `Seq Scan ... rows=250000`, `Buffers: shared hit=8131`, 94 мс. Индекс по `user_id`: `Bitmap Heap Scan`, 26 буферов, 0,13 мс на 20 строках. Индекс по `status` планировщик игнорирует: 25% таблицы — это 250 000 случайных чтений против 8131 последовательных, оценка стоимости индекса выше, и запрос снова идёт seq scan.

2. Работает: `WHERE user_id=42`; `WHERE user_id=42 AND status='paid'`; `WHERE user_id=42 AND status='paid' AND created_at > now()-interval '30 days' ORDER BY created_at DESC`. Бесполезен: только `status='paid'` (нет левого префикса); только диапазон по `created_at`; `WHERE user_id > 100 AND status='paid'` — диапазон по первой колонке ломает использование второй, дальше идёт фильтр.

3. `WHERE city='Москва' AND zip='101000'` при коррелированных колонках: планировщик перемножает селективности, оценивает `rows=250`, фактически 25 000 — расхождение в 100 раз, и вместо `Nested Loop` выбирается неверный `Hash Join`. Лечится `CREATE STATISTICS st_city_zip (dependencies, ndistinct) ON city, zip FROM addresses; ANALYZE addresses;` — оценка становится 24 800, план меняется.

4. Сессия 1: `UPDATE orders SET total=1 WHERE id=10;` затем `id=11`. Сессия 2 наоборот. Через секунду (`deadlock_timeout`) одна падает: `ERROR: deadlock detected`, `DETAIL: Process 158 waits for ShareLock on transaction 845; blocked by process 151`. Виновник — `SELECT pid, pg_blocking_pids(pid), query FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid))>0`. Лечение — единый порядок: обновлять `ORDER BY id`.

5. `LIMIT 20 OFFSET 800000`: `Sort Method: external merge Disk: 25488kB`, 412 мс, `temp read/written` около 25 МБ, буферов — десятки тысяч. Keyset `WHERE created_at < $1 ORDER BY created_at DESC LIMIT 20` по индексу: 54 мс, ноль temp, `Buffers: shared hit=25`. Разница в 7,6 раза и в гигабайтах temp на длинной выборке; цена — нельзя прыгнуть на произвольную страницу.

## Глава 39a. Бэкапы и восстановление

1. `pg_dump` 40 МБ/с: 200 000/40 = 5000 с ≈ 83 мин; канал 100 Мбит/с = 12,5 МБ/с: 200 000/12,5 = 16 000 с ≈ 267 мин; `pg_restore` 25 МБ/с: 8000 с ≈ 133 мин. RTO ≈ 483 мин ≈ 8 ч, и узкое место — не диск, а канал. `pg_basebackup` копирует файлы: 200 000/300 ≈ 11 мин плюс replay WAL. Приёмка: этапы посчитаны отдельно, узкое место названо, физическая копия укладывается в час.

2. `restic init`, три `restic backup /srv/data` с правкой 1% файлов. `restic stats --mode raw-data` → 2,04 ГБ при 6 ГБ логических данных, коэффициент 2,9×. Второй и третий снапшоты добавили по ~20 МБ: блоки режутся по содержимому (в среднем ~1 МиБ), неизменные 99% ссылаются на уже записанные пакеты. Приёмка: три снапшота в `restic snapshots`, raw-data < 2,2 ГБ, `restic check` без ошибок.

3. `pg_basebackup -D /var/backups/pg/base -Fp -Xs -P -R`, `archive_mode=on`, `archive_command='test ! -f /var/lib/pgwal/%f && cp %p /var/lib/pgwal/%f'`. `DROP TABLE orders`, затем `recovery_target_time='2026-10-29 11:58:00+00'`, `restore_command='cp /var/lib/pgwal/%f %p'`, `recovery_target_action='promote'`. Приёмка: таблица на месте, `pg_is_in_recovery()` = false, потеря ≤ 1 минуты.

4. Скрипт: `count(*)` по трём таблицам против прода, допуск `max(0.5%, суточный прирост × 2)`. Коды: 0 — сходится, 2 — расхождение данных, 3 — превышен `RTO_MIN`, 1 — технический отказ (нет доступа, пустой дамп). Приёмка: коды различимы в systemd, допуск выводится из прироста, время сравнивается с целью после smoke-теста.

5. Двенадцать сервисов: платежи (RPO 5 мин, RTO 1 ч, PITR), API (15 мин/2 ч), внутренние (24 ч/8 ч), аналитика (7 дней/48 ч). PITR не нужен шести: внутренние инструменты и аналитика терпят суточную потерю, данные восстановимы из источника (события в Kafka, выгрузки), а WAL-архив и прогретый стенд стоят денег. Приёмка: у каждого сервиса пять полей, шесть обоснованы, суммарная стоимость посчитана.

## Глава 41a. Helm и GitOps

1. `Chart.yaml`, `values.yaml` и `templates/app.yaml` (Deployment + Service + Ingress); `helm template shop ./charts/shop-api -f values-prod.yaml`. Меняются `image.tag`, `replicas`, `resources.limits`, `ingress.host`; остаются `metadata.name` через `fullname`, блок `labels`, порты Service, пути проб. Приёмка: `helm lint` чист, два рендера отличаются только ожидаемыми полями, `diff` объяснён построчно.

2. `_helpers.tpl` с `define "shop-api.labels"`, в шаблоне `{{- include "shop-api.labels" . | nindent 4 }}`; в Ingress `host: {{ required "ingress.host is required" .Values.ingress.host }}`. Без значения рендер падает: `Error: execution error at (shop-api/templates/app.yaml:41:14): ingress.host is required`, код 1. Приёмка: код 1, в тексте имя ключа, с `--set ingress.host=...` рендер проходит.

3. `base/` с общими манифестами, `overlays/staging` и `overlays/prod` с `images:` и `replicas` через патчи. Проще: смена тега, реплик, ресурсов — три строки в kustomization. Сложнее: условий и циклов нет, необязательный Ingress делают отдельным base или патчем с `$patch: delete`, а `required` заменяет `kubeconform` в CI. Приёмка: оба оверлея дают валидный YAML.

4. `argocd app create shop --repo ... --path deploy --dest-namespace shop --sync-policy automated --self-heal`. `kubectl scale deploy/shop-api --replicas=5` живёт до следующей сверки (по умолчанию 3 минуты), затем Argo возвращает значение из git: в UI `OutOfSync → Synced`, в событиях `self-heal`. Приёмка: откат ≤ 3 мин, `argocd app diff` пуст, действие в истории.

5. Коммит `8b2e7d4` с битым тегом → `ImagePullBackOff`, коммит `c3f9a1b` с исправлением → `Synced`. `git revert c3f9a1b` даёт `d41c0e5`, чей отрендеренный манифест равен ревизии до ошибки; `argocd app history shop` показывает три ревизии, у последней — `d41c0e5`. Приёмка: три записи в history, манифест совпадает, smoke-тест зелёный.

## Глава 42a. Нагрузочное тестирование

1. При `-c 50` и нулевом think time: `ab` ~3200 rps, p99 190 мс; `wrk -t4 -c50` ~18 500 rps, p99 65 мс; k6 ~9800 rps, p99 95 мс. Расхождение не про сервис: `ab` однопоточный и упирается в клиент, k6 тратит время на JS-рантайм и GC, `wrk` на epoll почти ничего не стоит. Приёмка: одинаковые `-c`, прогрев отброшен, CPU генератора < 70%, разброс p99 < 20% между прогонами.

2. `constant-vus` с 50 VU и задержкой 50 мс даёт потолок 1000 rps: когда сервис замедляется, VU сами ходят реже, темп падает и деградация маскируется. `ramping-arrival-rate` держит темп независимо от ответов, поэтому латентность и ошибки растут раньше. Приёмка: пиковая интенсивность та же, `dropped_iterations` = 0, колено видно на ступень раньше.

3. Пул на 10 соединений при 50 мс: `10 / 0,05 = 200 rps` — теоретическое колено. Таблица: 100 rps → p99 90 мс; 150 → 300 мс; 200 → 1500 мс; 250 → 6000 мс, ошибки 5%. Ресурс — не CPU (52%), а очередь за соединениями: `wait_count` в пуле, `idle in transaction` в `pg_stat_activity`. Приёмка: рабочая точка ≤ 70% колена, ресурс назван метрикой.

4. `pg_sleep(0.5)` в запросе при том же темпе: VU не успевают, k6 исчерпывает `maxVUs`, растёт `dropped_iterations`, фактический rps падает ниже целевого — тест недогружает сервис. В закрытой модели счётчика dropped нет: запросы копятся в VU, rps падает до `N / latency`, а latency включает ожидание в очереди клиента. Приёмка: dropped > 0, фактический rps приведён рядом с целевым.

5. С той же машины: p50 44 мс, p99 1100 мс; с отдельного хоста в той же сети: p50 46 мс, p99 780 мс. Плюс 2 мс — RTT сети, минус 300 мс хвоста — генератор больше не конкурирует за CPU и не делит conntrack с сервисом; на одной машине добавляются исчерпание эфемерных портов и `TIME_WAIT`. Приёмка: сценарий и данные те же, разница объяснена двумя причинами.

## Глава 43a. Секреты: Vault, SOPS, age

1. Env: `tr '\0' '\n' < /proc/1/environ` внутри, `docker inspect` и `ps e` снаружи, значение наследуют дочерние процессы. Файл `0400` из Secret: внутри читает только владелец, снаружи — root узла и любой с `kubectl get secret -o yaml` (base64). `emptyDir` с `medium: Memory`: tmpfs, в `docker inspect` и `/proc/*/environ` значения нет, но оно в RAM и видно root узла и в core dump. Приёмка: значения нет в трёх местах, ротация без рестарта.

2. `vault secrets enable -path=secret kv-v2`, `vault policy write shop-ro` с `path "secret/data/shop/api" { capabilities = ["read"] }`, `vault token create -policy=shop-ro -ttl=10m`. Через 10 минут `curl -H "X-Vault-Token: $T" .../v1/secret/data/shop/api` → `403 {"errors":["permission denied"]}`. Приёмка: 403 после TTL, политика только `read`, токен не `root`, чтения видны в аудите.

3. `.sops.yaml` с `encrypted_regex: ^(data|stringData|password|token|key)$`; `sops --encrypt --in-place values.yaml`. Меняем `image.tag` — в диффе одна открытая строка, остальные значения остаются `ENC[AES256_GCM,...]`. Расшифровка чужим ключом: `sops --decrypt --age <чужой> values.yaml` → `no identity matched any of the recipients`. Приёмка: дифф читаем, чужой ключ не работает, `.sops.yaml` в git.

4. `vault write database/roles/shop-api db_name=shop default_ttl=5m max_ttl=1h creation_statements="CREATE ROLE ... VALID UNTIL '{{expiration}}'"`. Открытое соединение после истечения живёт: PostgreSQL не рвёт сессии при `DROP ROLE`, но переподключение даёт `FATAL: password authentication failed`. Приёмка: старый пароль не пускает, `ConnMaxLifetime` меньше TTL, отказов в логах нет.

5. `git commit` с ключом → `gitleaks detect --source . --redact` находит `stripe_key` в `config.go:12` и в истории. Хронология: T0 коммит, T+4 мин детект в CI, T+9 мин отзыв в панели, T+15 мин новый ключ в Vault и выкатка, T+40 мин аудит показывает все чтения пути. Приёмка: gitleaks в CI, отзыв ≤ 15 мин, хронология из `vault audit` приложена.
