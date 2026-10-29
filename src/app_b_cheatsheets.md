# Приложение B. Шпаргалки

Команда, флаг и одна строка «когда звать». Всё, что здесь есть, выполняется локально без интернета.

## bash

### Параметры и подстановки

| Конструкция | Что делает и когда нужна |
|---|---|
| `"$@"` | все аргументы отдельными словами; `$*` склеивает их в одно — почти всегда ошибка |
| `${v:-def}` | значение по умолчанию, если пусто или не задано |
| `${v:=def}` | то же, но записывает результат в переменную |
| `${v:?msg}` | прервать скрипт с сообщением, если пусто |
| `${#v}` | длина строки |
| `${v%.*}` / `${v%%.*}` | срезать с конца первое / последнее расширение |
| `${v#*/}` / `${v##*/}` | срезать с начала до первого / последнего слэша (basename) |
| `${v/a/b}` / `${v//a/b}` | заменить первое / все вхождения без sed |
| `${v,,}` / `${v^^}` | нижний / верхний регистр (bash 4+) |
| `$(cmd)` | подстановка вывода; обратные кавычки не использовать |
| `((n++))` | арифметика; под `set -e` при результате 0 вернёт 1 — пишите `((++n))` |

### Условия и тесты

| Проверка | Когда |
|---|---|
| `[[ -f $p ]]` | файл существует; `-d` каталог, `-e` существует, `-s` непустой, `-x` исполняемый |
| `[[ -z $s ]]` / `[[ -n $s ]]` | строка пустая / непустая |
| `[[ $a == *.log ]]` | glob-сравнение; справа от `==` кавычки не ставят |
| `[[ $s =~ ^v([0-9]+)$ ]]` | regex, совпадение в `${BASH_REMATCH[1]}` |
| `(( a > b ))` | числовое сравнение; строки — `[[ $a < $b ]]` |
| `case $x in a) … ;; *) … ;; esac` | ветвление по шаблонам; варианты объединяются вертикальной чертой, читается лучше лестницы `elif` |
| `command -v jq >/dev/null` | проверить наличие команды, а не `which` |

### Редиректы и конвейеры

| Запись | Смысл |
|---|---|
| `> f` / `>> f` | перезаписать / дописать stdout |
| `2> f` | stderr в файл |
| `> f 2>&1` | stdout и stderr в файл; порядок важен, `2>&1 > f` ошибочен |
| `&> f` | то же короче (bash) |
| `2>&1` перед конвейером | stderr тоже уйдёт в конвейер |
| `2>/dev/null` | выбросить ошибки |
| `<<<"$s"` | here-string: строка на stdin без echo и конвейера |
| `cmd < <(other)` | process substitution: подставить вывод как файл |
| `tee -a log` | раздвоить поток: и на экран, и в файл |
| `find . -print0` + `xargs -0 -r -n1` | по одному аргументу, безопасно с пробелами в именах |
| `exec 3>f` … `>&3` | свой дескриптор, чтобы не смешивать выводы |

Оператор `cmd |& next` — короткая запись `cmd 2>&1 | next`: в конвейер уходят оба потока.

### Каркас скрипта

```bash
#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'
trap 'echo "fail at line $LINENO" >&2' ERR
```

`-e` не срабатывает внутри `if`, `while` и после `&&` — там код проверяют явно. `pipefail` нужен, иначе `false | true` вернёт 0.

## git

### Состояния и просмотр

| Команда | Когда |
|---|---|
| `git status -sb` | короткий статус плюс ветка и расхождение с upstream |
| `git diff` | рабочая копия против индекса |
| `git diff --staged` | индекс против HEAD — ровно то, что уйдёт в коммит |
| `git diff HEAD` | всё незакоммиченное сразу |
| `git log --oneline --graph --decorate -20` | история с ветками и тегами |
| `git show v1.4.2:app/main.py` | файл из коммита без переключения |
| `git stash -u` | отложить правки вместе с новыми файлами |

### Отмена

| Команда | Когда |
|---|---|
| `git restore f` | выбросить правки в файле, вернув версию из индекса |
| `git restore --staged f` | убрать из индекса, правки оставить |
| `git commit --amend --no-edit` | дописать в последний коммит без правки сообщения |
| `git revert <sha>` | коммит-отмена; единственный безопасный способ в общей ветке |
| `git reset --soft HEAD~1` | снять коммит, изменения оставить в индексе |
| `git reset --hard <sha>` | уничтожить рабочую копию — только для локального и с `reflog` в уме |
| `git reflog` | журнал перемещений HEAD: спасает после неудачного reset или rebase |
| `git restore --source=<sha> -- path` | вернуть файл из старого коммита |

### Поиск

| Команда | Когда |
|---|---|
| `git log -S'secret_key'` | коммиты, изменившие число вхождений строки (pickaxe) |
| `git log -G'regex'` | коммиты, где diff подходит под regex |
| `git log -L 40,60:app/main.py` | история конкретного диапазона строк |
| `git blame -w -C -L 10,20 f.py` | кто и когда, игнорируя пробелы и переносы |
| `git grep -n pattern v1.4.2` | поиск в старом теге |
| `git bisect start && git bisect run ./test.sh` | бинарный поиск ломающего коммита |

### rebase и публикация

```bash
git fetch --prune
git rebase -i origin/main                  # squash/fixup/reword
git rebase --autosquash -i HEAD~5          # подхватит fixup! и squash!
git rebase --onto main old-base feature    # перенести хвост на другую базу
git push --force-with-lease                # после rebase; не --force
```

`--force-with-lease` откажется пушить, если ветку успели обновить. Конфликт: правка → `git add` → `git rebase --continue`; выйти — `--abort`, пропустить — `--skip`.

## docker

### Жизненный цикл

| Команда | Когда |
|---|---|
| `docker run -d --name api -p 8080:8000 api:1.4.2` | запуск в фоне с публикацией порта |
| `docker ps -a` | все контейнеры; без `-a` только живые |
| `docker logs -f --tail 100 api` | логи; `--since 10m` — за последние 10 минут |
| `docker exec -it api sh` | зайти внутрь; `sh` есть всегда, `bash` не факт |
| `docker inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}}' api` | почему контейнер умер |
| `docker stats --no-stream` | CPU, память, сеть на текущий момент |
| `docker stop -t 30 api` | SIGTERM и 30 секунд до SIGKILL |
| `docker rm -f api` | удалить, даже если работает |
| `docker update --memory 512m api` | поменять лимит без пересоздания |

### Отладка

```bash
docker run --rm -it --entrypoint sh api:1.4.2   # осмотреться без CMD
docker run --rm -it --network container:api alpine sh  # сеть пода
docker cp api:/app/log.txt ./                   # достать файл
docker diff api                                 # правки в слое
docker history --no-trunc api:1.4.2             # команды и слои
```

Exit code 137 — SIGKILL или OOM, 143 — SIGTERM, 1 — ошибка приложения. Если контейнер падает сразу, `--entrypoint sh` покажет, есть ли вообще бинарник в образе.

### Очистка

| Команда | Когда |
|---|---|
| `docker system df` | сколько занимают образы, контейнеры, тома, кэш |
| `docker system prune -af --volumes` | снести всё неиспользуемое, включая тома |
| `docker image prune -a --filter until=168h` | образы старше недели |
| `docker builder prune -af` | кэш сборки — обычно самый большой потребитель |
| `docker volume ls -f dangling=true` | бесхозные тома |

### compose

| Команда | Когда |
|---|---|
| `docker compose up -d --build` | поднять и пересобрать изменённые сервисы |
| `docker compose ps` / `logs -f api` | состояние и логи одного сервиса |
| `docker compose exec api sh` | зайти в запущенный сервис |
| `docker compose config` | итоговый конфиг после merge и подстановок — проверять перед деплоем |
| `docker compose run --rm api pytest` | разовая команда в новом контейнере |
| `docker compose down -v` | остановить и удалить тома: данные пропадут |

## kubectl

### Чтение

| Команда | Когда |
|---|---|
| `kubectl get pods -o wide` | поды с нодой и IP |
| `kubectl get pods -A -l app=api --sort-by=.status.startTime` | фильтр по метке и сортировка по времени |
| `kubectl describe pod api-7d9f-x2` | события и причины: ImagePullBackOff, Unhealthy |
| `kubectl logs -f --tail=200 deploy/api` | логи по деплойменту |
| `kubectl logs api-7d9f-x2 --previous` | логи предыдущего, уже упавшего контейнера |
| `kubectl logs -l app=api --max-log-requests=10` | логи всех подов по селектору |
| `kubectl exec -it deploy/api -- sh` | внутрь пода |
| `kubectl port-forward svc/api 8080:80` | локально до сервиса без внешнего адреса |
| `kubectl cp api-7d9f-x2:/tmp/dump ./dump` | скопировать файл из пода |
| `kubectl top pods` / `top nodes` | потребление, нужен metrics-server |
| `kubectl auth can-i delete pods -n prod` | проверить права, а не гадать |
| `kubectl config current-context` | куда вы сейчас стреляете — смотреть перед `apply` |

### rollout

| Команда | Когда |
|---|---|
| `kubectl rollout status deploy/api --timeout=120s` | дождаться завершения выкатки в скрипте |
| `kubectl rollout history deploy/api` | ревизии; `--revision=3` — детали |
| `kubectl rollout undo deploy/api` | откат на предыдущую ревизию |
| `kubectl rollout restart deploy/api` | перезапуск без правки манифеста, чтобы подхватить ConfigMap |
| `kubectl scale deploy/api --replicas=5` | ручное масштабирование |

### Форматирование и события

```bash
 # имена, статусы и рестарты без шапки
kubectl get pods -o custom-columns=\
NAME:.metadata.name,PHASE:.status.phase,\
RESTARTS:.status.containerStatuses[0].restartCount --no-headers

 # образы всех контейнеров в namespace
kubectl get deploy -o custom-columns=\
NAME:.metadata.name,'IMAGE:.spec.template.spec.containers[*].image'

 # одно поле без YAML
kubectl get pod api-7d9f-x2 -o jsonpath='{.status.podIP}'

 # свежие события внизу
kubectl get events --sort-by=.lastTimestamp -A | tail -30
kubectl get events --field-selector reason=FailedScheduling
kubectl explain deploy.spec.strategy --recursive | head -30
```

`jsonpath` молча пропускает отсутствующие поля, а `-o yaml` надёжнее, когда структура незнакома.

### Отладка

```bash
kubectl debug -it api-7d9f-x2 --image=busybox --target=api  # в под
kubectl debug node/node-1 -it --image=busybox               # осмотр ноды
kubectl describe node node-1 | sed -n '/Allocated resources/,/Events/p'
```

## systemd

### Управление

| Команда | Когда |
|---|---|
| `systemctl status api.service` | состояние, последние строки журнала, PID |
| `systemctl restart api` / `reload api` | перезапуск / перечитать конфиг без обрыва |
| `systemctl enable --now api` | в автозапуск и запустить сразу |
| `systemctl list-units --failed` | что сломано на машине прямо сейчас |
| `systemctl list-timers --all` | таймеры и время следующего запуска |
| `systemctl cat api` | юнит и все drop-in'ы одним выводом |
| `systemctl edit api` | свой drop-in, не трогая чужой файл |
| `systemctl daemon-reload` | после правки юнита, иначе изменений не будет |
| `systemctl show api -p MainPID -p ExecMainStatus` | конкретные свойства для скриптов |

### journalctl

| Команда | Когда |
|---|---|
| `journalctl -u api -f` | живой лог сервиса |
| `journalctl -u api --since "10 min ago"` | за период; `-b -1` — за прошлую загрузку |
| `journalctl -u api -p err -o json-pretty` | только ошибки, структурой |
| `journalctl -u api -g 'timeout'` | regex по журналу, быстрее конвейера с grep |
| `journalctl -k -n 100` | ядро: OOM, сеть, диск |
| `journalctl --disk-usage` / `--vacuum-size=500M` | сколько занимает и как урезать |

### Шаблон юнита

```ini
[Unit]
Description=Shop API
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=app
WorkingDirectory=/opt/api
EnvironmentFile=/etc/api/env
ExecStart=/opt/api/api --config /etc/api/config.yaml
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=2s
TimeoutStopSec=30
LimitNOFILE=65535
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/api

[Install]
WantedBy=multi-user.target
```

`Type=notify` требует поддержки в приложении, иначе `simple`. Шаблон `api@.service` с `%i` даёт экземпляры: `systemctl start api@blue`.

## сеть

| Команда | Когда |
|---|---|
| `ss -tlnp` | кто слушает TCP и какой процесс |
| `ss -tanp state established` | установленные соединения по процессам |
| `ss -s` | сводка: сколько сокетов в каком состоянии |
| `ss -tin dst 10.0.0.5` | rtt, cwnd, ретрансмиты по конкретному пиру |
| `ip -br a` / `ip r` / `ip neigh` | адреса, маршруты, ARP-таблица кратко |
| `dig +short api.example.com` | только ответ |
| `dig api.example.com @1.1.1.1 +noall +answer` | спросить конкретный резолвер |
| `dig -x 10.0.0.5 +short` | обратная запись |
| `dig +trace example.com` | цепочка от корня: где ломается делегирование |
| `nc -zv host 5432` | жив ли порт, быстрее telnet |
| `mtr -rwc 20 host` | потери и задержка по хопам |
| `tcpdump -ni any port 443 -c 20 -A` | 20 пакетов с содержимым; `-w f.pcap` — в файл |
| `ethtool -S eth0` | счётчики ошибок и дропов; фильтруйте вывод по `err` |

### curl с таймингами

```bash
FMT='code=%{http_code} dns=%{time_namelookup} conn=%{time_connect}'
FMT="$FMT tls=%{time_appconnect} ttfb=%{time_starttransfer}"
FMT="$FMT total=%{time_total}\n"
curl -sS -o /dev/null -w "$FMT" https://api.example.com/health
```

`conn - dns` — сеть до сервера, `tls - conn` — рукопожатие (сертификат, CPU), `ttfb - tls` — работа бэкенда.

```bash
curl -v --http2 https://api.example.com/          # версия и заголовки
curl --resolve api.example.com:443:10.0.0.5 \
  https://api.example.com/                        # обойти DNS
curl -sS -H 'Content-Type: application/json' -d '{"a":1}' https://api/x
curl -sS --retry 3 --retry-delay 1 --max-time 10 https://api/health
curl -sSI https://api.example.com/ | head -1       # только заголовки и код
```

### TLS

```bash
openssl s_client -connect api.example.com:443 \
  -servername api.example.com </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates

openssl s_client -connect api.example.com:443 -tls1_3 \
  -servername api.example.com </dev/null 2>&1 | grep -E 'Protocol|Cipher'

echo | openssl s_client -connect api.example.com:443 2>/dev/null \
  | openssl x509 -noout -checkend 604800 && echo "живёт ещё неделю"
```

`-servername` обязателен: без SNI сервер отдаст не тот сертификат или дефолтный.

## python

| Команда | Когда |
|---|---|
| `python -m venv .venv && . .venv/bin/activate` | окружение проекта |
| `uv sync --frozen` | поставить ровно то, что в `uv.lock` |
| `uv add httpx` / `uv add --dev pytest` | добавить зависимость и обновить lock |
| `uv run pytest -q` | запуск в окружении проекта без активации |
| `uv lock --upgrade-package httpx` | точечное обновление одной зависимости |
| `python -m pip list --outdated` | что устарело |
| `python -X dev -W error app.py` | режим разработки: предупреждения как ошибки |
| `export PYTHONUNBUFFERED=1` | логи сразу в stdout, без буфера — обязательно в контейнере |

### pytest

| Флаг | Когда |
|---|---|
| `-x -q` | остановиться на первой ошибке |
| `-k "login and not slow"` | выбрать тесты по имени |
| `-m "not integration"` | выбор по маркерам |
| `--lf` / `--ff` | только упавшие / сначала упавшие |
| `-n auto` | параллельно, нужен pytest-xdist |
| `--cov=app --cov-report=term-missing` | покрытие с непокрытыми строками |
| `--durations=10` | самые медленные тесты |
| `-s --pdb` | показать print и встать в отладчик на падении |
| `--setup-show` | порядок фикстур, когда непонятно, что течёт |

## go

| Команда | Когда |
|---|---|
| `go build -trimpath -ldflags="-s -w" -o api ./cmd/api` | бинарник без путей сборки и отладочных символов |
| `GOOS=linux GOARCH=arm64 go build ./cmd/api` | кросс-компиляция под другую платформу |
| `go vet ./...` | подозрительный код до запуска тестов |
| `go test ./... -race -count=1` | тесты с детектором гонок, без кэша |
| `go test -run TestPay -v -count=1` | один тест |
| `go test -bench . -benchmem -run '^$'` | бенчмарки с аллокациями |
| `go test ./... -coverprofile=c.out` + `go tool cover -func=c.out` | покрытие; последняя строка — `total` |
| `go tool pprof -http=:8080 localhost:6060/debug/pprof/profile` | CPU-профиль за 30 секунд (`?seconds=30`) |
| `go tool pprof -http=:8080 localhost:6060/debug/pprof/heap` | топ по памяти |
| `go mod tidy` / `go mod why -m x` | привести зависимости в порядок / понять, кто тянет модуль |
| `go list -m -u all` | доступные обновления модулей |

```bash
 # стеки всех горутин: искать зависшие в select или на мьютексе
curl '127.0.0.1:6060/debug/pprof/goroutine?debug=2'
```

## Однострочники

```bash
ps -eo pid,pcpu,pmem,rss,cmd --sort=-pcpu | head -10  # кто ест CPU
du -xh --max-depth=1 /var | sort -h | tail -10        # что занимает диск
find /var/log -type f -size +100M -printf '%s %p\n'   # крупные файлы
lsof -i :8080 -sTCP:LISTEN                            # кто держит порт
jq -r '.items[] | [.name, .status] | @tsv' data.json  # JSON в таблицу
awk -F'"' '{print $2}' access.log | sort | uniq -c | sort -rn  # топ URL
tar -C /srv -czf - app | ssh host 'tar -C /srv -xzf -'  # каталог по SSH
journalctl --since -1h -p warning | wc -l             # предупреждения за час
```
