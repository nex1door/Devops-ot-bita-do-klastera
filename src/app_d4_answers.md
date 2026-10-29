# Приложение D. Ответы и решения — часть 4 (главы 33–44)

## Глава 33. HTTP-сервер и клиент

1. `mux.HandleFunc("GET /items/{id}", h)` — шаблон с методом сам отдаёт 405 и заголовок `Allow: GET, HEAD`. Валидация: `id, err := strconv.Atoi(r.PathValue("id"))`, при ошибке `Content-Type: application/json`, `w.WriteHeader(400)` и тело `{"error":"id must be an integer"}`. Проверка: `curl -i -X POST localhost:8080/items/1` → `405`, `Allow: GET, HEAD`.

2. `map[string]*bucket` под мьютексом, пополнение ленивое: `tokens = min(burst, tokens+elapsed.Seconds()*10)`; `burst=10` разрешает всплеск, поэтому в секунду проходит больше десяти. Отказ — `429` и `Retry-After: 1`. Проверка циклом `curl` с `-w '%{http_code}'` и `uniq -c`: ~10×200, остальные 429. Записи без обращений чистить, иначе map растёт от сканеров.

3. Повтор только для идемпотентных запросов и только на `503/429/5xx` и сетевые ошибки, три попытки, задержка `base << i` со сном `rand.Int63n(d)` — full jitter против синхронной волны. Перед повтором `io.Copy(io.Discard, resp.Body)` и `Close()`, иначе соединение не вернётся в пул. В логе 180 мс, затем 740 мс, третий запрос 200.

4. `signal.NotifyContext` + `srv.Shutdown` с таймаутом 15 с: новые соединения не принимаются, активные доигрывают — `hey -n 2000 -c 50` даёт ноль ошибок. С `WriteTimeout: 100ms` клиент видит `unexpected EOF`: дедлайн считается от конца чтения заголовков, запись обрывается, обработчик не отменяется и 503 отдать не может.

5. Отдельный мультиплексор на `127.0.0.1:6060` с `pprof.Index`. `go tool pprof -top 'http://localhost:6060/debug/pprof/goroutine?seconds=30'`: `net/http.(*conn).serve` — занятые обработкой (сходится с `-c`), `runtime.gopark` и `selectgo` — ждущие на канале, базе или мьютексе. Сотни ждущих при `-c 50` — утечка горутин.

## Глава 34. Базы данных в Go

1. `docker run -e POSTGRES_PASSWORD=secret postgres:17 -c max_connections=20`, `MaxOpenConns=0`, 200 параллельных → `pq: sorry, too many clients already` и 500 у части запросов, страдают и работающие поды. Лечение: `SetMaxOpenConns(15)`, `SetMaxIdleConns(15)`, `SetConnMaxLifetime(30*time.Minute)`; поды × соединений на под ≤ `max_connections` минус резерв.

2. Обёртка держит `atomic.Int64` и инкрементирует его в `QueryContext/ExecContext`, middleware пишет `db_queries_per_request`. N+1 — 101 запрос на страницу; исправление: собрать `ids` и `SELECT id, name FROM users WHERE id = ANY($1)` с `pq.Array(ids)`, разложить в map. Стало два запроса, p99 падает в разы.

3. `BeginTx` с `sql.LevelSerializable`; `UPDATE accounts SET balance = balance - $1 WHERE id = $2 AND balance >= $1`, проверка `RowsAffected()==1` иначе откат. До трёх повторов только на `40001` с паузой 20–100 мс и jitter. Проверка: 100 параллельных переводов, сумма неизменна, отрицательных нет, повторы видны в метрике.

4. `goose -dir migrations create add_order_status sql`: `ALTER TABLE orders ADD COLUMN status text NOT NULL DEFAULT 'new'`; отдельной миграцией `CREATE INDEX idx_orders_user_id` (для `CONCURRENTLY` — `-- +goose NO TRANSACTION`); затем `DROP COLUMN legacy_state`. `goose up`, `down`, `up` — всё Applied, `\d orders` подтверждает.

5. `/readyz` делает `db.PingContext` с таймаутом 2 с и отдаёт 503; liveness базу не проверяет, иначе под рестартует вместо выхода из балансировки. `docker stop pg` → после `failureThreshold: 2` при `periodSeconds: 5` под NotReady, IP уходит из `kubectl get endpoints api`, трафик не идёт. Запуск базы → возврат за ~10 с, `RESTARTS` остаётся 0.

## Глава 35. Тесты, бенчмарки, pprof, race detector

1. `tests := []struct{ name, in string; want int; wantErr bool }{...}` и `for _, tt := range tests { t.Run(tt.name, ...) }`. Один случай: `go test ./pkg -run 'TestParse/integer' -v` — слэш отделяет подтест, пробелы в имени заменяются подчёркиваниями. Новый кейс становится одной строкой в таблице, а не копией тела теста.

2. `go test -bench=Encode -benchmem -count=5 > old.txt`, буфер вынести в `var bufPool = sync.Pool{New: func() any { return new(bytes.Buffer) }}`, затем `benchstat old.txt new.txt`: `allocs/op` 4 → 0–1, падают `B/op` и `ns/op`. Оговорка: для мелких объектов `Pool` медленнее обычной аллокации, выигрыш только на дорогих объектах, уходящих в кучу.

3. `go test -bench=Handle -cpuprofile cpu.out`, затем `go tool pprof -top cpu.out` — верхние flat-строки обычно `runtime.mapaccess2_faststr`, `encoding/json.Marshal`, `compress/flate`. Догадку проверяем `go tool pprof -list=json.Marshal cpu.out`: стоимость разложена по строкам исходника, `-peek` показывает вызывающих, `-http=:8080` рисует граф.

4. `var n int` и сто горутин с `n++`, `go test -race` печатает `WARNING: DATA RACE` с двумя стеками и завершает прогон с ненулевым кодом. Исправления: `sync.Mutex` вокруг `n++` (~20 нс), `atomic.Int64.Add(1)` (~7 нс, лучший вариант для счётчика), канал или горутина-владелец (~100 нс, оправдан, когда нужен ещё и порядок).

5. Бесконечный `for { select { case <-ch: ...; case <-time.After(time.Second): } }` → `go test -timeout 30s` паникует дампом всех горутин. Лечение — бюджет: `ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)` и проверка `ctx.Err()`; запас на уборку — `context.WithDeadline(ctx, t.Deadline().Add(-2*time.Second))`. Падение становится assertion.

## Глава 36. Сборка и поставка

1. `CGO_ENABLED=0 go build` → `ldd` печатает `not a dynamic executable`; сборка с `CGO_ENABLED=1` линкует `libc.so.6`. В `FROM scratch` работает только статический, cgo падает с `no such file or directory`. Разница ~1 МБ, а резолвер разный: libc с `nsswitch.conf` против чистого Go с `/etc/resolv.conf`.

2. `go build -trimpath -buildvcs=false -ldflags "-s -w -X main.version=1.4.2 -X main.date=$(date -u -d @$(git log -1 --format=%ct) +%Y-%m-%dT%H:%M:%SZ)"`. `--version` → 1.4.2, `go version -m` печатает флаги. Две сборки дают одинаковый `sha256sum`; `date +%s` или отсутствие `-trimpath` ломают совпадение.

3. `docker buildx build --platform linux/amd64,linux/arm64 -t registry.example.com/api:1.4.2 --push .`, затем `docker buildx imagetools inspect registry.example.com/api:1.4.2` — индекс-манифест и два дочерних со своими digest. Мультиарх нельзя `--load`: ошибка про несколько платформ, нужен `--push` или `--output type=oci`.

4. `-s -w` даёт 15 МБ → ~10,5 МБ, `upx -9` — ~4 МБ. Но распаковщик разворачивает код в анонимные страницы: RSS выше на несколько мегабайт, страницы не делятся, core dump и символизация `pprof` ломаются, антивирус ругается, а в реестре выигрыш близок к нулю — образ и так жмётся gzip. Вывод: UPX не применять.

5. `syft "$IMAGE" -o cyclonedx-json=sbom.json` + `cosign attest --type cyclonedx --predicate sbom.json`; `cosign sign --yes "$IMAGE"@sha256:...`. Гейт: `cosign verify "$IMAGE"@sha256:... --certificate-identity-regexp '^https://github.com/org/repo/.github/workflows/release.yml@.*$' --certificate-oidc-issuer https://token.actions.githubusercontent.com`, ненулевой код останавливает деплой.

## Глава 37. Git: модель данных, ветки, rebase, хуки

1. `git cat-file -p HEAD` печатает `tree`, `parent`, автора, коммиттера и сообщение; `git cat-file -p HEAD^{tree}` — список `mode type hash name`. `git hash-object README.md` возвращает ровно тот же blob-хеш, что в дереве: хеш считается от `"blob <длина>\0"` плюс содержимое, без времени и имени файла. Отсюда же дедупликация блобов между ветками.

2. `git switch -c feat`, три коммита, `git rebase -i HEAD~3` — первый `pick`, остальные `squash`. Возврат: `git reflog` показывает `rebase (finish): returning to refs/heads/feat` и запись до неё, `git reset --hard feat@{1}` восстанавливает три коммита. Reflog живёт 90 дней, объекты через него достижимы — это и есть страховка от неудачного rebase.

3. `git config rerere.enabled true` заранее. Конфликт → правка → `git add` → `git rebase --continue`, решение оседает в `.git/rr-cache`; `git reset --hard ORIG_HEAD`; повторный rebase печатает `Resolved 'app.go' using previous resolution` и ничего не спрашивает. `git rerere status` и `git rerere diff` показывают, что именно запомнено.

4. `pre-commit`: `files=$(gofmt -l .); [ -z "$files" ] || { echo "$files"; exit 1; }`. `commit-msg`: `grep -qE '^[A-Z]+-[0-9]+' "$1" || { echo "нужен ABC-123"; exit 1; }`, оба `chmod +x`. `git commit --no-verify -m wip` проходит: хуки локальны и обходятся флагом, поэтому те же проверки дублируют в CI.

5. `git log -S 'AKIA' --oneline --all` находит коммит. Чистка: `git filter-repo --replace-text <(echo 'AKIA...==>REDACTED')`, затем `git reflog expire --expire=now --all && git gc --prune=now`; `git cat-file -e` на старый blob → `Not a valid object name`. Ключ всё равно отозвать: форки и кэши CI перезапись не получат.

## Глава 38. Docker: слои, Dockerfile, compose

1. `docker history --no-trunc --format '{{.Size}}\t{{.CreatedBy}}' api:old | sort -h | tail -3` — база, `apt-get install`, `COPY . .` с `node_modules` и `.git`. Вдвое: multi-stage, alpine или distroless, `--no-install-recommends` с удалением `/var/lib/apt/lists` в том же `RUN`, `.dockerignore`. 1,1 ГБ → 60–90 МБ.

2. Слои неизменяемы: `RUN apt-get install -y curl` добавляет ~12 МБ, следующий `RUN apt-get purge -y curl` пишет whiteout — файлы из нижнего слоя не удаляются, а маскируются. `docker history` показывает оба слоя, размер не меняется. Правильно ставить и удалять в одном `RUN`, а для отладки брать `kubectl debug`, не curl в проде.

3. Builder `python:3.14-slim` с `pip wheel -w /wheels -r requirements.txt`; runtime — тот же slim, `COPY --from=builder /wheels /wheels` и `pip install --no-cache-dir /wheels/*.whl`. Размер 1,1 ГБ → ~180 МБ, холодная сборка дольше из-за двух этапов; `RUN --mount=type=cache,target=/root/.cache/pip` возвращает тёплым пересборкам секунды.

4. Ключ — условие, а не список: `depends_on: {postgres: {condition: service_healthy}, redis: {condition: service_healthy}}`. Healthcheck: `pg_isready -U app -d app`, `redis-cli ping`, `wget -qO- localhost:8080/healthz`. После `up -d` все healthy, `RestartCount` равен 0. Без условий приложение стартует раньше базы и рестартует.

5. `docker run --memory=256m --memory-swap=256m` при 100 МБ даёт OOMKilled, код 137 и пустой лог. Понятная ошибка: `GOMEMLIMIT=200MiB` (80% лимита) плюс опрос `runtime.ReadMemStats`, на 85% — `WARN memory high` и `log.Fatal`, код 1. `docker inspect -f '{{.State.OOMKilled}} {{.State.ExitCode}}'` → `false 1`, сообщение в логах.

## Глава 39. CI/CD: пайплайны, кэш, артефакты

1. Три job: `lint` (`golangci-lint run`), `test` с `services.postgres` (`--health-cmd pg_isready`), `build` с `needs: [lint, test]` и buildx. Кэш: `actions/setup-go` с `cache: true` (ключ по `go.sum`) и `cache-from/to: type=gha,mode=max`. Холодный прогон 8 мин, повторный 3–4; в логах `Cache restored from key`. Вторая половина выигрыша — кэш слоёв buildx.

2. `strategy: {fail-fast: false, matrix: {python: ["3.13", "3.14"]}}`, версия подставляется `${{ matrix.python }}`. При `fail-fast: true` падение одной ветки отменяет соседнюю, и в гриде видно `cancelled`; с `false` обе доходят до конца, и видно, что ломается только 3.14, а 3.13 зелёный.

3. Сборка один раз, дальше продвижение по digest: job `build` отдаёт `outputs.digest`, деплой использует `image@${{ needs.build.outputs.digest }}` в dev, stage и prod; прод — `environment: production` с reviewers. Проверка: `kubectl -n dev get pod -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'` и то же в stage и prod — один sha256.

4. Argo Rollouts: `steps: [{setWeight: 10}, {pause: {duration: 5m}}, {setWeight: 100}]`; analysis с PromQL `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.01`, `interval: 1m`, `count: 5`, `failureLimit: 1`. При ошибках на канареечной версии Rollout уходит в `Degraded` и вес возвращается к нулю сам.

## Глава 40. IaC: Terraform и Ansible

1. `aws_s3_bucket` + `aws_s3_bucket_versioning` (`Enabled`) + `aws_s3_bucket_public_access_block` (все четыре `true`) + `tags`. Приёмка: второй `terraform plan` → `No changes. Your infrastructure matches the configuration.` Предложения изменений означают неописанный атрибут или ручную правку; дрейф отдельно виден в `plan -refresh-only`.

2. `backend "s3" { bucket = "tf-state-prod", key = "api/terraform.tfstate", dynamodb_table = "tf-locks", encrypt = true }`, затем `terraform init -migrate-state`. Второй параллельный `apply` → `Error: Error acquiring the state lock` и `ConditionalCheckFailedException` с ID владельца; state цел. В Terraform 1.10+ вместо DynamoDB — `use_lockfile = true`.

3. `apt: name=nginx state=present`; `template: src=site.conf.j2 dest=/etc/nginx/conf.d/site.conf` с `notify: reload nginx`; handler `service: name=nginx state=reloaded`. Первый прогон `changed=2`, второй `changed=0, failed=0` — это и есть критерий идемпотентности. `--check --diff` заранее показывает, что изменится, и не трогает handler.

4. `vars_files: [group_vars/vault.yml]`, файл шифруется `ansible-vault encrypt`, запуск с `--ask-vault-pass`. На задаче записи секрета `no_log: true`: в выводе, включая `-vvv`, значение заменяется на `the output has been hidden`. Проверка: `ansible-playbook site.yml -vvv | grep -c 'super-secret'` → 0. Без `no_log` секрет виден в diff результата.

## Глава 41. Kubernetes: поды, деплойменты, сервисы, probes

1. Deployment `replicas: 3`, метка `app: api`; Service `ClusterIP`, `selector: app: api`, `port: 80 → 8080`. `kubectl get endpoints api-svc` → три IP:8080. Селектор `app: api-v2` → `<none>`, endpointslices пуст: ClusterIP жив, но kube-proxy не знает бэкендов, клиент получает отказ. Поды Running — сломана связка Service→Pod.

2. Без startupProbe liveness с `initialDelaySeconds: 5`, `periodSeconds: 10`, `failureThreshold: 3` убивает под на ~35-й секунде при старте 40 с → `CrashLoopBackOff`, RESTARTS растёт. С `startupProbe: {periodSeconds: 5, failureThreshold: 12}` (бюджет 60 с) liveness и readiness не выполняются, пока она не прошла: под Ready один раз, `RESTARTS 0`.

3. `kubectl describe pod` → `Last State: Terminated, Reason: OOMKilled, Exit Code: 137`. 137 = 128+9: SIGKILL от ядра по лимиту cgroup, приложение ничего не пишет. Код 1 — собственный выход с ошибкой (паника, конфиг), в `Reason` будет `Error`. `kubectl get pod` при этом показывает `Running` с растущими RESTARTS: под перезапускается.

4. `maxUnavailable: 0` не даёт удалить старый под до Ready нового, новому нужна ёмкость → `Pending`, в describe `0/3 nodes are available: 3 Insufficient memory`. Варианты: снизить `requests` до реального потребления или добавить узел с autoscaler; либо `maxUnavailable: 1`, приняв просадку. Старые поды трафик держат.

## Глава 42. Наблюдаемость: метрики, логи, трейсы, SLO

1. `sum(rate(http_requests_total{job="api", code=~"5.."}[5m])) / sum(rate(http_requests_total{job="api"}[5m]))`. При остановке серий нет, результат — пустой вектор, а не ноль: `> 0.05` не даёт данных, алерт молчит при лежащем сервисе. Поэтому `absent(up{job="api"} == 1)` или `absent(sum(rate(...)))`: «нет данных» — отдельное состояние.

2. Бакеты `{.01,.025,.05,.1,.15,.2,.25,.3,.5,1,2,5}`, граница 0.3 обязательна. `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))`; точный p95 по логам — сортировка и элемент `ceil(0.95*n)-1`. Ошибка от линейной интерполяции внутри бакета 0.3–0.5 достигает 10–20% и у границы SLO меняет вердикт.

3. Серий столько же, сколько пар пользователь×метрика: 10 тыс. × 20 = 200 тыс., при 3–4 КБ на серию это 600–800 МБ RSS. Смотреть `prometheus_tsdb_head_series` и `process_resident_memory_bytes` на шагах 100/1k/10k. Проблема наступает, когда серии растут быстрее трафика: scrape дольше интервала, запросы таймаутят. `user_id` — в логи и трейсы.

4. Burn rate = доля ошибок / бюджет 0,001, то есть 20 при двух процентах. Быстрый (14,4× за 1 ч) сработает через ~43 минуты устойчивых 2%: окно разбавляет начало. Медленный (6× за 6 ч) — только через часы. Пара даёт скорость и точность: короткое окно ловит пик, длинное — тихую деградацию, которую пик не показывает.

5. A делает `Extract` из `traceparent`, создаёт span и `Inject` в заголовки исходящего запроса. Если B берёт `context.Background()` или забывает `Inject`, он стартует новую трассировку: в Jaeger вместо одного дерева из двух вложенных span'ов появляются две трассы с разными `trace_id` и пустым `parent_id`, waterfall разорван, число трейсов удвоилось.

## Глава 43. Безопасность и supply chain

1. `docker run --rm img id` → `uid=0(root)`. Лечение: `RUN useradd -r -u 10001 app` и `USER 10001`; securityContext `runAsNonRoot`, `runAsUser: 10001`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `drop: ["ALL"]`. Падает с `read-only file system` на `/tmp` и кэше — им нужны `emptyDir`. `kubectl exec -- id` → 10001.

2. `trivy image --severity HIGH,CRITICAL api:1.4.2` даёт 41 находку, с `--ignore-unfixed` — 12: разница это CVE без исправленной версии в базе, обновление пакетов их не уберёт. Порог «ноль» на живом образе недостижим; гейт — `--ignore-unfixed --exit-code 1 --severity CRITICAL` плюс исключения с датой истечения.

3. `syft api:1.4.2 -o cyclonedx-json=sbom.json`, затем `jq '.components[] | select(.name=="golang.org/x/net") | {name, version, purl}'` → `v0.40.0`, purl `pkg:golang/golang.org/x/net@v0.40.0`. По одному образу ответ за секунды; по сорока образам без Dependency-Track — часы на вытягивание манифестов, без SBOM — грепать `go.sum` по репозиториям.

4. `cosign sign --yes api@sha256:...`, затем `cosign verify api@sha256:... --certificate-identity=dev@example.com --certificate-oidc-issuer=https://token.actions.githubusercontent.com`. Неверная идентичность → `Error: no matching signatures`, код 1. Сертификат Fulcio получит любой, привязку к пайплайну дают только identity и issuer; проверять по digest.

5. Только `http`/`https`; резолв через `net.Resolver`; отклонить 127/8, 10/8, 172.16/12, 192.168/16, 169.254/16, `::1`, fc00::/7. Диалектить по разрешённому IP (иначе DNS rebinding обходит проверку), без редиректов или с проверкой каждого хопа, тело через `io.LimitReader`. `169.254.169.254` и домен на 10.0.0.5 → 400 `destination not allowed`.

## Глава 44. Инциденты, postmortem, on-call

1. SEV1 — полный отказ, потеря данных или утечка: все на связи, IC сразу, апдейт каждые 15 мин. SEV2 — ключевая функция: IC и владелец, 30 мин. SEV3 — деградация: дежурный, час. SEV4 — тикет. Если на трёх прошлых инцидентах реакция не совпала с уровнем, критерий расплывчат: заменить слова числами.

2. `kubectl scale deploy api --replicas=2`: клиенты не замечают, ошибок нет, латентность +20–30% из-за меньшей ёмкости. Признак — только `up{job="api"} == 0` и `kube_deployment_status_replicas_available`. MTTD — до срабатывания алерта с `for: 2m` (3:20), MTTR — до возврата реплики (4:10). MTTD выше пяти минут означает, что алерта на `up` нет.

3. Влияние: 1240 ошибок за 8 минут, 3% оформлений, данных не потеряно. Таймлайн UTC: 10:02 конфиг, 10:04 5xx, 10:07 алерт, 10:09 IC, 10:16 откат, 10:20 восстановление. Причина: `/health` стал отдавать 500, под выведен, ёмкость — две реплики. Actions: `up==0` (Иванов, 05.11), `minReplicas: 3` и PDB (Петров, 07.11), проба на `/readyz` (Сидоров, 03.11).

4. `fallocate -l 5G /fill`; симптомы — `DiskPressure`, evictions, `no space left on device` при pull. Диагностика: `df -h`, `du -xhd1 /var | sort -h`, `journalctl --disk-usage`, `crictl rmi --prune`. Удалить файл, флаг снимется за ~5 минут. Без консоли помог бы DaemonSet с `hostPath: /` и `nsenter` либо serial console — и то и другое готовят до инцидента.

5. Page — только если есть влияние на пользователей и действие нужно в минуты. «Диск 80%», «сертификат истекает через 30 дней», «рестарты > 5 за час» без нарушения SLO — тикеты. Из 24 page-алертов остаются 15, 9 переводятся в тикеты: звонков было ~7 в неделю, стало ~2. Пересматривать раз в месяц, иначе тикеты копятся и теряются.
