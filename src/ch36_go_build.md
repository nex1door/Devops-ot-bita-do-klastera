# Глава 36. Сборка и поставка

Go компилируется в один самодостаточный бинарник, и это меняет всю цепочку поставки: нет интерпретатора, нет виртуального окружения, нет `node_modules`. Но у этой простоты есть цена — размер, воспроизводимость и то, что версию в бинарник никто не положит за вас. В главе разбирается, как собрать статический бинарник, вшить в него версию и коммит, собрать под чужую архитектуру, сделать сборку воспроизводимой, упаковать в контейнер на десяток мегабайт и подписать результат.

## Статический бинарник: CGO_ENABLED=0

По умолчанию `go build` на Linux линкует бинарник с libc, если в проекте есть cgo (например, `net` с системным резолвером или `os/user`). Такой бинарник зависит от версии glibc на хосте, и перенос в контейнер на Alpine даёт классическую ошибку `not found or not executable`, потому что musl и glibc несовместимы.

```bash
CGO_ENABLED=0 go build -o bin/api ./cmd/api
file bin/api
ldd bin/api
```

```text
bin/api: ELF 64-bit LSB executable, x86-64, statically linked, Go BuildID=...
	not a dynamic executable
```

`CGO_ENABLED=0` отключает cgo и заставляет стандартную библиотеку использовать чистые Go-реализации: DNS-резолвер читает `/etc/resolv.conf` сам, `os/user` разбирает `/etc/passwd`, вместо системного `getaddrinfo`. Компромисс: `/etc/nsswitch.conf` и экзотические источники имён (LDAP, SSSD) перестают работать, а разрешение имён идёт по `resolv.conf` с таймаутами Go, а не системными. Для Kubernetes этого достаточно; если нужна интеграция с корпоративным NSS — оставляйте cgo и собирайте на том же дистрибутиве, что и рантайм.

Исключение — драйверы с обязательным cgo (например, `github.com/mattn/go-sqlite3`). Тогда либо статическая линковка с musl, либо чистый Go-аналог `modernc.org/sqlite` (глава 34).

## Версия в бинарнике: ldflags -X

Версия, которую видно в `api --version` и в логах старта, — первый вопрос при разборе инцидента. Вшивается она линкером в строковую переменную пакета `main`:

```go
var (
	version = "dev"
	commit  = "none"
	date    = "unknown"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "--version" {
		fmt.Printf("api %s (%s, %s)\n", version, commit, date)
		return
	}
	slog.Info("starting", "version", version, "commit", commit)
	// запуск сервера
}
```

Сборка подставляет значения вместо дефолтов:

```bash
go build -trimpath -buildvcs=false \
  -ldflags "-s -w \
    -X main.version=$(git describe --tags --always --dirty) \
    -X main.commit=$(git rev-parse --short HEAD) \
    -X main.date=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -o bin/api ./cmd/api
```

`-X` работает только со строковыми переменными и только если они не константы. Проверить, что попало в бинарник, можно без запуска:

```bash
go version -m bin/api
```

```text
bin/api: go1.26.10
	path	example.com/api/cmd/api
	mod	example.com/api	(devel)
	build	-trimpath
	build	CGO_ENABLED=0
	build	GOOS=linux
	build	GOARCH=amd64
	build	vcs.revision=3f9c1ab...
```

`go version -m` печатает модуль, зависимости и настройки сборки — этого часто достаточно, чтобы понять, из какого коммита собран образ. Дублирующая информация есть и в рантайме: `debug.ReadBuildInfo()` отдаёт `vcs.revision` и `vcs.time`, если сборка шла с `-buildvcs=true` (по умолчанию — да, если каталог под git).

## Кросс-компиляция

Кросс-компиляция в Go не требует тулчейнов: стандартная библиотека собирается под целевую платформу тем же компилятором.

```bash
GOOS=linux   GOARCH=arm64 CGO_ENABLED=0 go build -o bin/api-linux-arm64 ./cmd/api
GOOS=darwin  GOARCH=arm64 CGO_ENABLED=0 go build -o bin/api-darwin-arm64 ./cmd/api
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -o bin/api.exe ./cmd/api
```

| `GOOS` | `GOARCH` | Куда |
|---|---|---|
| `linux` | `amd64` | x86-серверы, большинство облаков |
| `linux` | `arm64` | Graviton, Ampere, Raspberry Pi |
| `darwin` | `arm64` | Apple Silicon, ноутбуки разработчиков |
| `windows` | `amd64` | утилиты для админов |

Ограничение ровно одно: с `CGO_ENABLED=1` кросс-компиляция требует кросс-линкера под целевую платформу, и это уже не «одна команда». Для `linux/amd64` полезно знать про `GOAMD64`: уровень `v1` — базовый и совместим со всем, `v2` добавляет SSE4.2 и POPCNT, `v3` — AVX2 и BMI2; собирать с `v3` в публичный образ нельзя: часть инстансов упадёт с `SIGILL`.

## Воспроизводимые сборки

Воспроизводимая сборка (reproducible build) — та, что из одного коммита даёт побайтово одинаковый бинарник. Это позволяет проверить, что в реестре лежит именно собранное из исходников, а не что-то ещё.

```bash
go build -trimpath -buildvcs=false -ldflags "-s -w" -o /tmp/api1 ./cmd/api
go build -trimpath -buildvcs=false -ldflags "-s -w" -o /tmp/api2 ./cmd/api
sha256sum /tmp/api1 /tmp/api2
go version -m /tmp/api1 | head -3
```

```text
6d1f5b1e0c2f9a7...  /tmp/api1
6d1f5b1e0c2f9a7...  /tmp/api2
```

Три вещи ломают воспроизводимость: абсолютные пути в отладочной информации (лечится `-trimpath`), VCS-стамп с временем и грязным деревом (`-buildvcs=false` или сборка из чистого архива) и переменная `-ldflags "-X main.date=..."` с текущим временем. Последнее противоречие кажется неразрешимым, но решается передачей времени коммита: `date -u -d @$(git log -1 --format=%ct)`.

## Размер бинарника и почему UPX вреден

Типичный HTTP-сервис на Go — 12–20 МБ. `-ldflags="-s -w"` убирает таблицу символов и DWARF и даёт минус 25–30%:

```bash
go build -o /tmp/api-full ./cmd/api
go build -ldflags "-s -w" -o /tmp/api-stripped ./cmd/api
ls -lh /tmp/api-full /tmp/api-stripped
```

```text
-rwxr-xr-x 1 dev dev 18M api-full
-rwxr-xr-x 1 dev dev 13M api-stripped
```

Дальше обычно вспоминают про UPX. Делать этого не стоит. UPX сжимает бинарник самомодифицирующимся распаковщиком: при старте он разворачивает код в память, из-за чего ломаются core dumps и профилирование, растёт потребление памяти (страницы становятся анонимными и не делятся между процессами), антивирусы в корпоративных контурах ругаются на упакованный ELF, а выигрыш в реестре почти нулевой — образ и так сжимается gzip при передаче, и сжатый UPX-бинарник весит примерно столько же. Экономия в 30% размера образа не окупает потерю диагностики в инциденте.

## Multistage Dockerfile

Компилятор в образ не нужен: собираем в одном слое, копируем бинарник в пустой.

```dockerfile
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -buildvcs=false \
    -ldflags "-s -w -X main.version=${VERSION}" -o /out/api ./cmd/api

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/api /api
USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/api"]
```

`COPY go.mod go.sum` отдельным слоем до `COPY . .` — главный трюк: пока зависимости не менялись, слой с `go mod download` берётся из кэша, и пересборка после правки одной строки кода занимает секунды. `distroless/static` содержит корневые сертификаты и `/etc/passwd`, но не содержит шелла — это одновременно меньше поверхность атаки и меньше 5 МБ. Если нужен `scratch`, сертификаты копируют руками:

```dockerfile
FROM scratch
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=build /out/api /api
ENTRYPOINT ["/api"]
```

## buildx и несколько платформ

Обычный `docker build` собирает только под архитектуру хоста. Для мультиарх-образа нужен buildx с эмуляцией через QEMU:

```bash
docker buildx create --name multi --use
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg VERSION=1.4.2 \
  --cache-from type=gha --cache-to type=gha,mode=max \
  -t registry.example.com/api:1.4.2 --push .

docker buildx imagetools inspect registry.example.com/api:1.4.2
```

```text
Name:      registry.example.com/api:1.4.2
MediaType: application/vnd.oci.image.index.v1+json
Manifests:
  Platform:    linux/amd64
    Digest:    sha256:3b1e...
  Platform:    linux/arm64
    Digest:    sha256:9f2c...
```

Сборка под arm64 на amd64-хосте идёт через эмуляцию и потому медленная; в CI её ускоряют нативными раннерами под каждую платформу. Результат — манифест-список, и `docker pull` сам выберет нужный образ. Тег `:latest` для продакшена не используют: деплоят по {{L|g28|digest}} `@sha256:...`.

## Подпись и SBOM в двух словах

Поставка не заканчивается сборкой образа. Минимум: сгенерировать SBOM (список компонентов) и подписать образ.

```bash
syft registry.example.com/api:1.4.2 -o spdx-json > sbom.json
cosign sign --yes registry.example.com/api@sha256:...
cosign attest --yes --predicate sbom.json --type spdxjson registry.example.com/api@sha256:...
```

Подпись привязывается к digest, а не к тегу, поэтому подменить образ под тем же тегом незаметно не получится. Проверка в кластере — через admission policy (глава 43), которая отклоняет образы без валидной подписи.

## Типичные ошибки

1. **`CGO_ENABLED=1` и базовый образ `scratch`.** Бинарник требует libc, которой в образе нет; контейнер падает с `no such file or directory` при старте. Собирайте статически или берите образ с libc.
2. **Версия только в теге образа.** Тег перезаписывается, и через месяц невозможно понять, что работало в инциденте; версия должна быть в бинарнике и в `go version -m`.
3. **`-ldflags "-X"` для не-строки.** Линкер молча не подставит значение в `int` или `const`, и в бинарнике останется дефолт.
4. **Сборка без `-trimpath`.** Пути вида `/home/ivan/work/api` попадают в бинарник: сборки не совпадают побайтово, а в стектрейсах светится структура каталогов разработчика.
5. **UPX «для экономии».** Ломаются core dumps и профилирование, растёт потребление памяти, а размер образа в реестре почти не меняется.
6. **`COPY . .` до `go mod download`.** Любая правка кода инвалидирует слой с зависимостями, и сборка каждый раз качает модули заново.
7. **`:latest` в деплое.** Откат невозможен, потому что непонятно, на что откатываться; деплойте по digest.

## Чек-лист

- [ ] `CGO_ENABLED=0` и проверка `ldd` показывают «not a dynamic executable».
- [ ] `--version` печатает версию, коммит и дату сборки.
- [ ] `go version -m` на готовом бинарнике показывает нужный `vcs.revision`.
- [ ] Сборка идёт с `-trimpath`, две сборки из одного коммита совпадают по `sha256sum`.
- [ ] Размер бинарника измерен, `-s -w` применён, UPX не используется.
- [ ] В {{L|g30|Dockerfile}} `go.mod`/`go.sum` копируются до исходников.
- [ ] Образ собирается под `linux/amd64` и `linux/arm64`, деплой идёт по digest.
- [ ] Для образа есть SBOM и подпись, привязанная к digest.

## Упражнения

1. Соберите сервис с `CGO_ENABLED=0` и с `CGO_ENABLED=1`, сравните `ldd`, размер и поведение при запуске в `scratch`.
2. Вшейте версию через `-X`, проверьте `--version` и `go version -m`; затем попробуйте подставить время коммита вместо текущего и добейтесь совпадения `sha256sum` у двух сборок.
3. Соберите мультиарх-образ через buildx и проверьте манифест командой `docker buildx imagetools inspect`.
4. Возьмите бинарник 15 МБ, примените `-s -w` и UPX, замерьте размер, потребление RSS при старте и возможность снять heap-профиль. Объясните результат.
5. Настройте в CI генерацию SBOM и подпись cosign, затем проверьте подпись командой `cosign verify` перед деплоем.

*Ответы и разбор к этим упражнениям — в приложении D, часть 4.*
