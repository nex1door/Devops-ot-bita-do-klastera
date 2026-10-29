# Приложение D. Ответы и решения — часть 3 (главы 21–32)

Все ответы проверены на локальном стенде: Python 3.13, bash 5.2, Go 1.26.10. Выводы в ответах — реальные результаты запусков, а не ожидаемые.

## Глава 21. Сеть и API на Python

1. `fetch(url, timeout=5.0)` держит `urlopen` в `try` с тремя ветками: `HTTPError` → `(e.code, e.read())`, `(URLError, OSError)` → `(0, str(e))`, успех → `(r.status, r.read())`. Проверено на локальном сервере: 200, 404 и таймаут 1 с дают `(200, …)`, `(404, …)`, `(0, …)`, наружу не летит ничего. У httpx то же самое — одна строка `client.get()` при уже настроенном `Timeout(5)`.

2. В `retry_after`: если `raw.isdigit()` — `int(raw)`; иначе `email.utils.parsedate_to_datetime(raw)` и `max(0, int((dt - now_utc).total_seconds()))`. Проверено: `"120"` → 120, дата «сейчас + 60 с» → 59 (дробная часть отбрасывается), мусор → `default`. Без `tzinfo=UTC` у naive-даты вычитание бросает `TypeError`.

3. Бюджет — скользящее окно 60 с: `deque` из `(ts, is_retry)`, перед повтором выбрасываем старые метки и считаем долю. Если `retries/total > 0.1`, повтора нет — сразу `ApiError`. При исчерпании лучше отдать ошибку наверх, чем ждать: бюджет общий на процесс, и пауза останавливает все воркеры.

4. `allow()` пускает, пока `opened_at is None`; пятая подряд неудача в `record()` открывает цепь на 30 с, затем пропускается ровно один пробный запрос, успех сбрасывает счётчики. На `MockTransport` с 503 первые 10 вызовов из 13 попыток до сети дошли 9, остальные отсеклись мгновенно; пробный после паузы получил 200 и закрыл цепь.

## Глава 22. Файлы, конфиги, логирование

1. `tail` идёт от конца блоками по 8 КБ: `f.seek(0, 2)`, затем назад, пока `buf.count(b"\n") <= n`, результат — `splitlines()[-n:]`. На файле 1 ГБ (≈21 млн строк) вышло 0.1 мс и maxrss 10.4 МБ, то есть память не зависит от размера файла. Неравенство `<= n` нужно из-за завершающего перевода строки.

2. `merge_configs` делает `out = dict(base)` и рекурсивно сливает только словари: `isinstance(v, dict) and isinstance(out.get(k), dict)`. Списки и скаляры заменяются целиком: `tags: ["c"]` перетёр `["a","b"]`, а `db.opts` стал `{ssl: true, timeout: 5}`. Исходный `base` не изменился — на каждом уровне создаётся новый словарь.

3. Фильтр обходит структуру рекурсивно и заменяет значение, если `k.lower() in {"password","token","authorization"}`; в `logging.Filter` переписывается `record.msg`, а `record.args` обнуляется. Проверено на вложенности и списке: `password`, `nested.token` и `list[0].Authorization` стали `***`, остальные поля не тронуты.

4. Ротация: `shutil.copyfileobj` в `gzip.open(..., "wb")`, затем пустой файл через `os.replace` (атомарнее, чем `truncate`), потом удаление `*.gz` со `st_mtime` старше 14 суток. Проверено: архив за сегодня создан, лог стал 0 байт, файл 20-дневной давности удалён, свежий остался.

## Глава 23. Тесты: pytest

1. `@pytest.mark.parametrize` на шесть пар: `0s→0`, `1h1h→7200`, `999999d→86 399 913 600`, `2d3h4m5s`. Отдельный параметризованный тест на `ValueError`: `""`, `"15"`, `"1x"`, `"1h30"`, `"1H"`. Итог — 15 тестов за 0.04 с. `1h1h` проходит, потому что парсер суммирует все токены, а не берёт последний.

2. Фикстура подменяет `time.monotonic` и `time.sleep` через `monkeypatch.setattr`; `time` импортируется самим тестируемым модулем, поэтому подмена видна его коду. `wait_ready(5.0, poll=0.25)` даёт ровно 20 итераций и `expired=True` за миллисекунды: виртуальные часы двигает заглушка `sleep`, реального ожидания нет.

3. `asyncio.sleep` подменяется корутиной, собирающей аргументы, а транспорт считает обращения. Проверено: при трёх 503 `len(calls) == 3` и `slept == [0.5, 1.0]`, тест идёт 0.01 с. Проверять нужно и число попыток, и задержки — иначе тест зелёный и при ретраях без backoff.

4. Строка `max(0, int(...))` в `retry_after` была покрыта, но не проверена: тесты подавали только будущие даты, клампинг не срабатывал. Новый тест с датой в прошлом требует 0 и падает, если убрать `max`. Покрытие ветвей этого не видит: обе ветки исполнены, а поведение не проверено.

## Глава 24. CLI и упаковка

1. `cmd_status` печатает `json.dumps({...}, sort_keys=True)` при `--json`, иначе `занято мест: N` и строки `seat -> owner`; `return EXIT_OK` в обеих ветвях. Проверено: stdout `{"holds": {"12A": "alice"}, "seats": 1}`, rc=0. `sort_keys` даёт стабильный вывод для тестов и диффов.

2. Тест: `hold`, затем `before = st.read_bytes()`, `mtime = st.stat().st_mtime_ns`, вызов `--dry-run release 12A` → rc=0, `read_bytes() == before`, `mtime` тот же. Сверять только байты мало: `save` может перезаписать файл идентичным содержимым, и mtime ловит именно это.

3. На `typer` вышло 79 строк против 96: исчезли `build_parser` и `set_defaults`, типы берутся из аннотаций. Коды сохранены явно — `raise typer.Exit(3)`, диагностика — `typer.echo(..., err=True)`. Проверено: конфликт даёт rc=3 и сообщение в stderr, `status --json` отдаёт тот же JSON.

4. `pip wheel . -w dist` → `seatctl-1.4.0-py3-none-any.whl`; в чистом venv `pip install --no-index --find-links dist seatctl`, из `/tmp` команда `seatctl --version` печатает `seatctl 1.4.0`. В контейнере то же плюс `--no-cache-dir`. Работает за счёт `[project.scripts]`: без точки входа файла в `bin/` не будет.

5. Job `build`: `pip wheel`, сверка версии с тегом, `twine upload --repository-url $INDEX`. Job `verify`: `pip install --index-url $INDEX seatctl==$VERSION` и `seatctl --version`. Разделение гарантирует, что проверяется именно опубликованный артефакт, а не локальная сборка из соседнего каталога.

## Глава 25. Шелл: переменные, кавычки, подстановки

1. `dir=${p%/*}` (если слэша нет, результат равен `$p` — подставляем `.`), `f=${p##*/}`, дальше `base=${f%.*}` и `ext=${f##*.}` только при `[[ $f == *.* ]]`. Проверено: `/var/log/syslog.bak` → `/var/log|syslog|bak`, `report.txt` → `.|report|txt`, `/etc/hosts` → `/etc|hosts|` (расширения нет).

2. `while IFS= read -r h; do printf '<%s>\n' "$h"; done < hosts` печатает по строке на хост: `<web 01>`, `<db*>`. Вариант `for h in $(cat hosts)` сначала режет вывод по IFS, а потом раскрывает glob: `web 01` превращается в два элемента, а `db*` — в список файлов каталога.

3. `a=(alpha beta gamma delta epsilon); a+=(zeta)` → `${#a[@]}` = 6, `printf '%s\n' "${a[@]}"` печатает по одному в строку. Ассоциативный: `declare -A http=([200]="OK" [404]="Not Found" …); http[429]="Too Many Requests"` даёт 4 элемента, обход `"${!http[@]}"` неупорядочен, поэтому `| sort -n`.

4. `die() { printf '%s\n' "${1:-ошибка}" >&2; exit "${2:-1}"; }`; проверка: `[[ -n ${TOKEN:-} ]] || die "нет TOKEN" 2`. `${2:-1}` подставляет код 1, а `exit` внутри функции завершает весь скрипт, а не только функцию — поэтому `die` нельзя вызывать в `$(...)`.

5. Правило: кавычки вокруг каждой подстановки, `--` перед путями, `find … -print0 | xargs -0`, вместо `$(ls)` — glob `for f in ./*`. До правки shellcheck ругается на неквотированное `$(ls)` (SC2046) и переменные без кавычек (SC2086), после — чисто. В каталоге с `a b.txt`, `*star`, `-n` неквотированный цикл видит пять «файлов» вместо трёх.

## Глава 26. Управляющие конструкции и коды возврата

1. `is_number() { [[ $1 =~ ^-?[0-9]+$ ]]; }` на `12abc` даёт 1. Арифметический вариант `(( $1 ))` печатает `((: 12abc: value too great for base (error token is "12abc")` и тоже возвращает 1, но шумит в stderr, спотыкается на `08` (восьмеричная запись) и считает `0` ложью. Для валидации входа годится только regex.

2. Ручной цикл: `while (($#)); do case $1 in --env=*) env=${1#*=} ;; --env) env=$2; shift ;; --) shift; rest+=("$@"); break ;; -*) die "флаг $1" 2 ;; *) rest+=("$1") ;; esac; shift; done`. Проверено: `--env=prod` и `--env stage` дают одинаковый результат, неизвестный `-x` → rc=2. `getopts` длинные опции не умеет.

3. В `if f; then …` `set -e` отключён на всём теле `f`: после `false` печатается «после false внутри f», функция возвращает 0, скрипт идёт дальше. Прямой вызов `g` с тем же `false` завершает скрипт с rc=1, и «НЕ ДОСТИГНУТО» не печатается. Лечится `|| return 1` после каждого шага.

4. `case ${f##*.} in json) tool=jq ;; yaml|yml) tool=yq ;; csv) tool=awk ;; *) echo "нет инструмента: $f" >&2; exit 3 ;; esac`. Проверено: три файла разобраны (`jq`, `yq`, `awk`), `notes.txt` даёт rc=3 и сообщение в stderr. Явный `exit 3` нужен потому, что код по умолчанию — 1, а 3 отличает «неизвестный формат» от прочих сбоев.

5. `until code=$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 2 "$url"); do (( SECONDS < deadline )) || exit 1; sleep 1; done`. `set -e` не срабатывает: команда стоит в условии `until`. Проверено на сервере с 503/503/200: два сообщения curl об ошибке, успех через 2.0 с, rc=0.

## Глава 27. Текст: grep, sed, awk, jq, xargs, find

1. Сортировка вставками прямо в `END`:

```bash
awk -F: '$3>=1000{n++;u[n]=$1;id[n]=$3}
END{for(i=2;i<=n;i++){t=id[i];s=u[i];for(j=i-1;j>0&&id[j]>t;j--){id[j+1]=id[j];u[j+1]=u[j]} id[j+1]=t;u[j+1]=s}
for(i=1;i<=n;i++)print u[i],id[i]}' /etc/passwd
```

Вывод совпал с `sort -k2,2n`: `nextdoor 1000`, `nobody 65534`. POSIX awk не имеет `sort`, поэтому «без sort» — ручная сортировка (в gawk есть `asort`, но он непортируем). Порядок у `awk` не гарантирован, потому что он обходит вход последовательно и индекс не хранит.

2. Поля формата combined: 1 — IP, 9 — код, 11 — секунды.

```bash
awk '{n[$1]++; if($9>=500) e[$1]++; if($11>m[$1]) m[$1]=$11}
END{for(ip in n) printf "%-12s %4d %4d %7.3f\n", ip, n[ip], e[ip]+0, m[ip]}' access.log | sort -k3,3nr
```

`e[ip]+0` обязателен: у IP без 5xx поле пустое. Вывод: `10.0.0.2 2 2 2.500`, `10.0.0.1 3 1 1.204`, `10.0.0.3 1 0 0.008`.

3. `sed -E '/^[[:space:]]*#/d; s/^[[:space:]]*([A-Za-z0-9_.]+)[[:space:]]*=[[:space:]]*(.*)$/\U\1\E=\2/'`. Проверено: `key = value` → `KEY=value`, `empty =` → `EMPTY=`, комментарий удалён, `DB_HOST = db.local` → `DB_HOST=db.local`. `\U…\E` — расширение GNU sed, в BSD/macOS нужен perl или `tr`.

4. `jq -sc 'group_by(.env)[] | {env: .[0].env, total: (map(.dur)|add)}' builds.ndjson` даёт `{"env":"prod","total":24}` и `{"env":"stage","total":3.0}`. Дальше `jq -r 'select(.ok|not) | .id' builds.ndjson | xargs -r curl -fsS -X POST https://ci.example/builds/` — id уходят аргументами по одному.

5. `find /var/log -type f -mtime +14 -print0 > list`; размер — `xargs -0 -r stat -c %s < list | awk '{s+=$1} END{print s}'`; удаление — `xargs -0 -r rm -f -- < list` под `(( DRY_RUN ))`. NUL обязателен из-за имён с переводом строки. Проверено на каталоге с `b c.log`: 2 файла, 4000 байт.

## Глава 28. Процессы, сигналы, перенаправления

1. Запуск в фоне с накоплением PID, затем `for p in "${pids[@]}"; do if wait "$p"; then echo "$p: 0"; else echo "$p: $?"; rc=1; fi; done; exit "$rc"`. Проверено: `586838: 0`, `586839: 7`, `586840: 0` и общий rc=1. Ждать нужно по PID: `wait` без аргументов вернул бы код только последнего задания.

2. Порядок редиректов решает всё, потому что `2>&1` копирует текущее значение fd 1:

| вариант | stdout | stderr |
|---|---|---|
| `>log 2>&1` | файл | файл |
| `2>&1 >log` | файл | терминал |
| `>log` | файл | терминал |
| `2>log` | терминал | файл |

Во втором случае `2>&1` сработал до `>log`, поэтому stderr остался на терминале; в файле только `out`.

3. `arr=(); while IFS= read -r h; do arr+=("$h"); done < <(gen_hosts)` — подстановка процесса вместо пайпа. Пайп выполнил бы `while` в подоболочке, и массив умер бы вместе с ней. Проверено: `${#arr[@]}` = 2, `arr[1]` = `b c`, значения с пробелом целы.

4. `trap on_term TERM INT` с флагом `stopping`: первый SIGTERM пишет в fd 3 и ставит флаг, второй делает `exit 143`; `trap on_hup HUP` только перечитывает конфиг. Проверено: в логе старт, HUP, TERM, повторный TERM, rc=143. `exec 3>>log` держит дескриптор отдельно, stdout и stderr остаются свободными.

5. `nohup ./worker.sh &`: после `kill -9` процесс исчезает навсегда, поднимать некому, в `nohup.out` остаётся хвост без причины смерти. systemd с `Restart=on-failure` перезапустит юнит через `RestartSec`; `systemctl status` и journal покажут `code=killed, status=9/KILL`, `systemctl show -p NRestarts` — счётчик.

## Глава 29. Практика: скрипты бэкапа, healthcheck, деплоя, systemd timers

1. Проверка ключа идёт первой строкой, до `mkdir` и `tar`: `gpg --batch --list-keys "$RECIPIENT" || { echo "нет ключа" >&2; exit 3; }`. Дальше `tar -czf - dir | gpg --batch --yes -e -r "$RECIPIENT" -o "$tmp"` и `mv` в финальное имя. Проверено: без ключа rc=3 и ни одного файла, с ключом архив расшифровывается в исходное дерево.

2. Цикл по конфигу копит `failed+=("$url ($code)")`, в конце один `logger -t healthcheck "упало N: …"` и `exit 1`. Тонкость: `code=$(curl … || true); code=${code:-000}` — curl сам печатает `000` при отказе, и `|| echo 000` даёт `000000`. Проверено: из четырёх эндпоинтов упали два, оба попали в алерт с кодами.

3. После `ln -sfn releases/$NEW current` — десять запросов на `127.0.0.1:$PORT` (порт релиза, мимо прокси), считаем не-200; `(( bad * 100 > 10 * n ))` при `n=10` → `ln -sfn releases/$OLD current` и `exit 1`. Значит, допустима ровно одна ошибка из десяти — это стоит проговорить в ревью.

4. `hc.timer`: `OnCalendar=*:0/5`, `AccuracySec=30s`, `Unit=hc.service`; `hc.service`: `Type=oneshot`, `ExecStart=/usr/local/bin/healthcheck.sh`, `TimeoutStartSec=20`. `systemd-analyze verify` проходит, ругаясь только на отсутствующий бинарь, `systemd-analyze calendar '*:0/5'` печатает `*-*-* *:00/5:00`.

5. Частые провалы: нет `flock` — при `Persistent=true` два бэкапа пишут в один файл; нет `TimeoutStartSec` — зависший `tar` блокирует следующий запуск; относительный путь в `ExecStart` даёт `WorkingDirectory=/` и «файл не найден»; нет `trap … EXIT` — `.part` остаётся после обрыва.

## Глава 30. Go: начало

1. `go mod init example.com/lab/hello`, `main.go` печатает `runtime.Version()` и `runtime.NumCPU()`: `go: go1.26.10`, `cpus: 8`. Обычная сборка — 2 406 230 Б, с `-trimpath -ldflags="-s -w"` — 1 585 314 Б (−34%). `-s -w` убирает таблицы символов и DWARF, `-trimpath` — абсолютные пути в бинаре.

2. `internal/greet/greet.go` с `func Hello(name string) string` и тест в том же каталоге: `go test ./...` → `ok example.com/lab/hello/internal/greet`. Импорт из чужого модуля даже с `replace` даёт `use of internal package example.com/lab/hello/internal/greet not allowed` — это проверка компилятора, а не соглашение.

3. `mux.HandleFunc("GET /healthz", …)` пишет `ok`; `/version` отдаёт `json.NewEncoder(w).Encode(map[string]string{"go": runtime.Version(), "build": buildTime})`, а `var buildTime = "unknown"` переопределяется `-ldflags "-X main.buildTime=$(date -u +%FT%TZ)"`. Проверено: `ok` и `{"build":"2026-10-29T16:47:40Z","go":"go1.26.10"}`; `POST /healthz` → 405.

4. `CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build …` → `ELF 64-bit LSB executable, ARM aarch64, statically linked`; `GOOS=windows GOARCH=amd64` → `PE32+ executable (console) x86-64`. `.exe` Go добавляет, только когда имя выбирает сам (`go build ./cmd/hello` → `hello.exe`); при явном `-o hello-windows` суффикса не будет.

5. Шаг CI: `test -z "$(gofmt -l .)" || { gofmt -d .; exit 1; }`, затем `go mod tidy` и `git diff --exit-code go.mod go.sum`. Проверено: неформатированный файл валит первый шаг, после `gofmt -w` проходит. Порядок — от дешёвого к дорогому: fmt, tidy (сеть), vet, тесты, сборка.

## Глава 31. Синтаксис: срезы, мапы, указатели, интерфейсы, ошибки

1. `Dedup` пишет в новый срез, поэтому вход не мутируется:

```go
func Dedup(in []string) []string {
	seen := make(map[string]struct{}, len(in))
	out := make([]string, 0, len(in))
	for _, s := range in {
		if _, ok := seen[s]; ok {
			continue
		}
		seen[s] = struct{}{}
		out = append(out, s)
	}
	return out
}
```

Тест сверяет и результат `[b a c]` для `[b a b c a]`, и то, что исходный срез остался из пяти элементов. `make(..., 0, len(in))` даёт одну аллокацию вместо роста.

2. Поля — `rows, cols int` и `data []float64`. `Set` обязан быть на указателе: он меняет данные, и на копии структуры запись потерялась бы. `At` и `Transposed` приёмник не меняют, но указатель дешевле:

```go
func (m *Matrix) At(r, c int) float64     { return m.data[r*m.cols+c] }
func (m *Matrix) Set(r, c int, v float64) { m.data[r*m.cols+c] = v }

func (m *Matrix) Transposed() *Matrix {
	t := &Matrix{rows: m.cols, cols: m.rows, data: make([]float64, len(m.data))}
	for r := 0; r < m.rows; r++ {
		for c := 0; c < m.cols; c++ {
			t.data[c*t.cols+r] = m.data[r*m.cols+c]
		}
	}
	return t
}
```

3. `type Store interface { Get(string) ([]byte, error); Put(string, []byte) error }`. `MemStore` — мапа под `sync.RWMutex`; `DirStore` — `os.ReadFile`/`os.WriteFile` с обёрткой `errors.Is(err, fs.ErrNotExist) → ErrNotFound`. Функция `Copy(dst, src Store, key string) error` работает с любым: обе реализации проходят проверку `var _ Store = …`.

4. `var ErrNotFound, ErrConflict = errors.New("не найдено"), errors.New("конфликт")`, `type ValidationError struct{ Field string }` с методом `Error()`. В обработчике первым идёт `errors.As(err, &ve)` → 422, затем `errors.Is` для 404 и 409, иначе 500. `As` нужен раньше: тип-ошибка не совпадёт с sentinel по `Is`, но обёрнута через `%w`.

5. `Recover(next)` — `defer func(){ if v := recover(); v != nil { log.Printf("panic: %v\n%s", v, debug.Stack()); w.WriteHeader(500) } }()`. Тест на `httptest`: путь `/boom` даёт 500, следующий запрос на `/live` — 200, сервер жив. Паника в горутине обработчика этот middleware не поймает — она уронит процесс.

## Глава 32. Конкурентность: горутины, каналы, context

1. На каждый источник — горутина-пересыльщик, общий `WaitGroup` закрывает результат:

```go
func Merge(chans ...<-chan int) <-chan int {
	out := make(chan int)
	var wg sync.WaitGroup
	wg.Add(len(chans))
	for _, ch := range chans {
		go func(c <-chan int) {
			defer wg.Done()
			for v := range c {
				out <- v
			}
		}(ch)
	}
	go func() { wg.Wait(); close(out) }()
	return out
}
```

Проверено на трёх каналах, один из которых отдаёт значение через 20 мс: получены все четыре значения, канал закрылся сам.

2. Ограничение — буферизованный `sem := make(chan struct{}, limit)` с `defer func(){ <-sem }()`; ошибки копятся в срез под `sync.Mutex` и возвращаются `errors.Join(errs...)`. Тест на `httptest` со счётчиком активных запросов под `atomic`: пик не превысил 2 при `limit=2`, оба 503 попали в `errors.Join`, прогон под `-race` чистый.

3. Профиль отдаёт `3 @ 0x… main.main.func1.1 … main.go:18` — три горутины в одной точке. Стек читают снизу вверх: последняя строка — ваш код, выше — стандартная библиотека. `chan send` в этой строке означает горутину, ждущую читателя, которого нет: канал создан, но `range`/`<-` по нему не запущен.

4. `select { case <-time.After(10 * time.Second): fmt.Fprintln(w, "done"); case <-ctx.Done(): return }`. `curl --max-time 1` получил rc=28, а в логе появилось `отменён: context canceled` сразу после разрыва: `r.Context()` закрывается вместе с соединением, и работа прекращается, а не считается вхолостую.

5. На 8-ядерной машине: мьютекс 20.3 / 92.2 / 120.1 нс на 1/4/8 горутинах, атомик 12.8 / 18.0 / 21.0 нс. Мьютекс сериализует горутины и на 8 даёт в 5.7 раза хуже; атомик не блокирует, а крутит CAS на кэш-линии, поэтому деградация мягкая. Разница видна только при высокой частоте операций.

**Сводка по главам (упражнений / ответов)**

| Глава | Упражнений | Ответов |
|---|---|---|
| 21 | 4 | 4 |
| 22 | 4 | 4 |
| 23 | 4 | 4 |
| 24 | 5 | 5 |
| 25 | 5 | 5 |
| 26 | 5 | 5 |
| 27 | 5 | 5 |
| 28 | 5 | 5 |
| 29 | 5 | 5 |
| 30 | 5 | 5 |
| 31 | 5 | 5 |
| 32 | 5 | 5 |
| **Итого** | **57** | **57** |
