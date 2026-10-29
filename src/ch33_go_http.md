# Глава 33. HTTP-сервер и клиент

Стандартная библиотека Go содержит полноценный HTTP-сервер и клиент: `net/http` не требует фреймворка, поддерживает HTTP/1.1 и HTTP/2 (второй — автоматически при TLS), пул соединений, таймауты и корректное завершение. Именно поэтому на Go пишут экспортёры, вебхуки, sidecar-прокси и внутренние API: сервис на 300 строк без единой внешней зависимости — норма, а не подвиг. Но у `net/http` есть свойство, о котором узнают в инциденте: значения по умолчанию рассчитаны на «работает и не падает», а не на «устойчив к враждебной сети». В этой главе мы соберём сервис с обработчиками, middleware, идентификатором запроса, таймаутами и остановом по `SIGTERM`, а затем — клиент с пулом соединений, таймаутами и осмысленными повторами.

## Сервер: мультиплексор и обработчики

Обработчик (handler) — это всё, что умеет `ServeHTTP(http.ResponseWriter, *http.Request)`. `http.HandlerFunc` превращает обычную функцию в обработчик. Мультиплексор (`ServeMux`) сопоставляет путь и метод с обработчиком.

С Go 1.22 шаблоны стали выразительнее: в них можно указать метод и переменные пути.

```go
mux := http.NewServeMux()
mux.HandleFunc("GET /healthz", handleHealth)
mux.HandleFunc("GET /items/{id}", func(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")   // значение из пути
	fmt.Fprintf(w, "item %s\n", id)
})
mux.HandleFunc("POST /items", handleCreate)
mux.HandleFunc("GET /files/{path...}", handleFiles) // {path...} — остаток пути
```

Шаблон `GET /items/{id}` не совпадёт с `POST /items/42` — вернётся 405 с заголовком `Allow`, а не 404. Это заметно упрощает API: не нужно вручную разбирать `r.Method` в каждом обработчике.

Глобальный `http.DefaultServeMux` и функции `http.HandleFunc` удобны в примерах, но в сервисе лучше создавать свой мультиплексор. Причина в том, что `DefaultServeMux` — глобальная переменная, и любой импортированный пакет может зарегистрировать в ней путь при инициализации (так делают `net/http/pprof` и некоторые библиотеки). В результате маршрут появляется в вашем API неявно, а тесты, поднимающие два сервера, конфликтуют за одни и те же пути.

## Middleware

Middleware — функция, принимающая обработчик и возвращающая обработчик. Так как обработчик — это интерфейс с одним методом, обёртки складываются в цепочку без магии.

```go
type Middleware func(http.Handler) http.Handler

func Chain(h http.Handler, mws ...Middleware) http.Handler {
	for i := len(mws) - 1; i >= 0; i-- { // последний в списке — ближе всего к обработчику
		h = mws[i](h)
	}
	return h
}
```

Порядок применения обратный порядку перечисления: `Chain(h, A, B)` даёт `A(B(h))`, то есть `A` видит запрос первым, а `B` — первым ответ. Это важно для логирования: middleware, снимающий метрики по времени, должен стоять снаружи, иначе он не учтёт время, потраченное внешними обёртками.

Логирование требует знать код ответа, а `http.ResponseWriter` его не отдаёт. Решение — обёртка, запоминающая статус:

```go
type statusRecorder struct {
	http.ResponseWriter
	status int
	bytes  int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

func (r *statusRecorder) Write(p []byte) (int, error) {
	if r.status == 0 {
		r.status = http.StatusOK // неявный 200 при первой записи
	}
	n, err := r.ResponseWriter.Write(p)
	r.bytes += n
	return n, err
}
```

Без такой обёртки в логах будет `status=0` для всех успешных ответов, потому что обработчик не вызывает `WriteHeader` явно. И ещё: обёртка ломает доступ к `http.Flusher` и `http.Hijacker`, если не реализовать их проброс — для SSE и {{L|g129|WebSocket}} это критично.

## Таймауты: почему сервер без них уязвим

`http.Server` с нулевыми таймаутами не имеет ограничений по времени вообще. Клиент может открыть соединение, отправить один байт заголовка и молчать — сервер будет держать соединение и горутину, пока клиент не отвалится по своему таймауту (или никогда). Это атака Slowloris: несколько тысяч таких соединений исчерпывают лимит файловых дескрипторов (типичный `LimitNOFILE` в systemd-юните — 1024, если не поднят), и сервер перестаёт принимать новые подключения.

```go
srv := &http.Server{
	Addr:              ":8080",
	Handler:           handler,
	ReadHeaderTimeout: 5 * time.Second,   // защита от Slowloris
	ReadTimeout:       15 * time.Second,  // весь запрос: заголовки + тело
	WriteTimeout:      30 * time.Second,  // от заголовков до конца записи
	IdleTimeout:       90 * time.Second,  // keep-alive простаивающего соединения
	MaxHeaderBytes:    1 << 20,           // 1 МиБ на заголовки
}
```

Смысл каждого параметра разный, и путать их — типичная ошибка. `ReadHeaderTimeout` ограничивает только чтение заголовков и закрывает самый дешёвый вектор Slowloris. `ReadTimeout` — всё чтение запроса целиком, включая тело; если сервис принимает большие загрузки, его надо увеличивать или использовать `http.MaxBytesReader` вместе с ним. `WriteTimeout` отсчитывается от конца чтения заголовков запроса; для долгих стриминговых ответов он станет ограничением, и тогда его поднимают или управляют дедлайном через `http.ResponseController` (появился в Go 1.20). `IdleTimeout` не даёт простаивающим {{L|g59|keep-alive}} соединениям копиться; если он ноль, используется `ReadTimeout`.

Таймаут сервера — грубая защита уровня соединения. Точная — дедлайн на обработку запроса:

```go
func withTimeout(d time.Duration, h http.Handler) http.Handler {
	return http.TimeoutHandler(h, d, `{"error":"timeout"}`)
}
```

`http.TimeoutHandler` возвращает 503, если обработчик не успел, но не прерывает его: горутина продолжает работу, пока не завершится сама. Настоящая отмена делается через `r.Context()`, который отменяется при разрыве соединения клиентом и при `Shutdown`.

## Graceful shutdown

При деплое под приходит `SIGTERM`. Если процесс завершится немедленно, клиенты получат оборванные соединения, а балансировщик — ошибки 502. Правильное поведение: перестать принимать новое, доработать текущие запросы, затем выйти.

```go
func run(srv *http.Server) {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer stop()

	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("listen: %v", err)
		}
	}()

	<-ctx.Done() // пришёл SIGTERM
	stop()       // восстанавливаем обработку сигналов: второй SIGTERM убьёт процесс

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("shutdown: %v", err)
	}
}
```

`Shutdown` закрывает слушающие сокеты, закрывает простаивающие соединения и ждёт завершения активных, пока не истечёт переданный контекст. `ListenAndServe` при этом возвращает `http.ErrServerClosed` — это нормальный код выхода, поэтому его нельзя логировать как ошибку и нельзя вызывать `log.Fatal` на нём.

Таймаут в `shutdownCtx` должен быть меньше, чем `terminationGracePeriodSeconds` в Kubernetes (по умолчанию 30 секунд), иначе под получит `SIGKILL` до того, как сервер закончит. Практика: время на остановку 15–20 секунд при grace period 30 — остаётся запас на сбор логов и выход.

Отдельная деталь: `SIGKILL` перехватить нельзя, поэтому «мы ловим все сигналы» — неверная формулировка. Ловят `SIGTERM` и `SIGINT`; `SIGKILL` — последняя мера ядра.

## Клиент

`http.DefaultClient` не имеет таймаута. Запрос к недоступному хосту может висеть минутами, удерживая горутину и соединение; в сервисе с высокой нагрузкой это исчерпывает пул и память. Свой клиент — обязателен.

```go
var httpClient = &http.Client{
	Timeout: 10 * time.Second, // весь запрос: соединение, редиректы, чтение тела
	Transport: &http.Transport{
		DialContext:           (&net.Dialer{Timeout: 3 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		TLSHandshakeTimeout:   3 * time.Second,
		ResponseHeaderTimeout: 5 * time.Second,
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   20, // по умолчанию 2
		IdleConnTimeout:       90 * time.Second,
		ForceAttemptHTTP2:     true,
	},
}
```

`Client.Timeout` покрывает всё: установку соединения, TLS-рукопожатие, отправку, ожидание заголовков, чтение тела. Это удобно, но у него есть следствие: таймаут срабатывает и во время чтения тела, поэтому для больших ответов нужен либо больший `Timeout`, либо отказ от него в пользу `context.WithTimeout` на конкретный запрос.

`MaxIdleConnsPerHost` по умолчанию равен 2. Для сервиса, который делает десятки параллельных запросов к одному API, это означает постоянные новые TCP-соединения и TLS-рукопожатия; поднятие до 20–50 обычно даёт кратный выигрыш по задержке. `Transport` нужно переиспользовать: создание нового на каждый запрос лишает вас пула и оставляет висеть простаивающие соединения до сборки мусора.

## Повторы

Повтор запроса — операция с побочными эффектами, если метод не идемпотентен. Повторять `GET`, `HEAD`, `PUT`, `DELETE` при сетевой ошибке и кодах 502/503/504 разумно; `POST` — только если сервис поддерживает ключ идемпотентности. Ответ 429 повторяют, уважая `Retry-After`.

```go
func doWithRetry(ctx context.Context, req *http.Request) (*http.Response, error) {
	backoff := 200 * time.Millisecond
	for attempt := 0; attempt < 4; attempt++ {
		resp, err := httpClient.Do(req.Clone(ctx))
		switch {
		case err != nil && ctx.Err() != nil:
			return nil, ctx.Err() // отмена важнее повтора
		case err != nil:
			// сетевая ошибка — повторяем
		case resp.StatusCode < 500 && resp.StatusCode != http.StatusTooManyRequests:
			return resp, nil
		default:
			io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20)) // дочитать и закрыть
			resp.Body.Close()
		}

		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(backoff):
		}
		backoff *= 2
	}
	return nil, errors.New("retries exhausted")
}
```

Три вещи, без которых повтор вредит. Тело ответа нужно дочитать и закрыть перед повтором, иначе соединение не вернётся в пул. `req.Clone(ctx)` нужен, потому что тело запроса одноразовое: повторная отправка того же `*http.Request` с непустым `Body` отправит пустое тело. И задержка должна расти, иначе при массовом сбое все клиенты синхронно добьют уже падающий сервис — к экспоненте добавляют джиттер.

## Полный сервис

Соберём всё вместе: маршруты, middleware с request id и логом, таймауты, `/healthz` и `/readyz`, останов по `SIGTERM`.

```go
func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK) // liveness: процесс жив
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), time.Second)
		defer cancel()
		if err := checkDeps(ctx); err != nil { // готовность принимать трафик
			http.Error(w, "not ready", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	})

	h := Chain(mux, RequestID, AccessLog, Recoverer)

	srv := &http.Server{
		Addr:              envOr("ADDR", ":8080"),
		Handler:           h,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       90 * time.Second,
		BaseContext:       func(net.Listener) context.Context { return context.Background() },
	}
	run(srv) // функция с signal.NotifyContext и Shutdown из раздела выше
}
```

Разница между проверками принципиальна для Kubernetes. `healthz` (liveness) отвечает «процесс жив и не завис»: если она падает, {{L|g62|kubelet}} перезапускает под. `readyz` (readiness) отвечает «можно слать трафик»: если недоступна БД, под выводится из балансировки, но не перезапускается. Ошибка новичков — проверять в liveness зависимости, из-за чего падение БД вызывает лавину перезапусков всех подов и полный отказ сервиса.

Middleware `RequestID` берёт идентификатор из заголовка `X-Request-ID` (если его прислал прокси) или генерирует новый, кладёт в контекст и в заголовок ответа — тогда один и тот же идентификатор виден и в логах сервиса, и в логах балансировщика, и в ответе клиенту.

Проверка работоспособности:

```bash
go build -o /tmp/svc . && /tmp/svc &
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/healthz
kill -TERM %1
sleep 1; jobs
```

Ожидаемый вывод — `200`, после `kill` процесс выходит с кодом 0 и освобождает порт: активные запросы доработаны, новые не принимаются.

## Типичные ошибки

**Сервер без таймаутов.** Нулевые значения означают «ждать вечно»: Slowloris держит горутины и дескрипторы, пока не кончится `LimitNOFILE`. Механизм — `net.Conn` без дедлайна; лечится `ReadHeaderTimeout` плюс `ReadTimeout`.

**`log.Fatal` на `http.ErrServerClosed`.** При штатном завершении `ListenAndServe` возвращает эту ошибку, и `log.Fatal` превращает нормальный выход в код 1. В {{L|g115|systemd}} это выглядит как падение; проверяйте `errors.Is(err, http.ErrServerClosed)`.

**Отсутствие `defer resp.Body.Close()`.** Тело ответа держит соединение; без закрытия транспорт не возвращает его в пул, и после нескольких сотен запросов клиент упирается в лимит сокетов. Механизм — соединение освобождается только после `Close` и полного чтения тела.

**Повтор неидемпотентного запроса.** Повтор `POST` создаёт дубликат заказа или платежа. Механизм — сервер не отличает повтор от нового запроса без ключа идемпотентности. Повторяйте только идемпотентные методы или передавайте `Idempotency-Key`.

**Новый `http.Client` на каждый вызов.** Каждый клиент создаёт свой `Transport` со своим пулом; соединения не переиспользуются, растёт число рукопожатий и {{L|g117|TIME_WAIT}} сокетов. Клиент и транспорт создаются один раз и живут всё время работы процесса.

**`Shutdown` без таймаута.** `srv.Shutdown(context.Background())` ждёт активные запросы бесконечно; зависший обработчик не даст процессу выйти, и под получит `SIGKILL` от kubelet. Контекст остановки обязан иметь дедлайн меньше grace period.

**Обёртка `ResponseWriter`, теряющая интерфейсы.** `statusRecorder` без `Flush`/`Hijack` ломает SSE и WebSocket: обработчик приводит `w` к `http.Flusher` и получает `ok=false`. Нужно реализовать проброс или использовать `http.ResponseController`.

## Чек-лист

- [ ] У `http.Server` заданы `ReadHeaderTimeout`, `ReadTimeout`, `WriteTimeout`, `IdleTimeout`.
- [ ] Используется собственный `ServeMux`, а не `DefaultServeMux`.
- [ ] Есть `/healthz` (liveness, без зависимостей) и `/readyz` (readiness, с проверкой зависимостей).
- [ ] `SIGTERM` обрабатывается через `signal.NotifyContext`, `Shutdown` ограничен таймаутом меньше grace period.
- [ ] `http.ErrServerClosed` не логируется как ошибка.
- [ ] Клиент создан один раз, `Timeout` задан, `MaxIdleConnsPerHost` поднят под нагрузку.
- [ ] Тело каждого ответа закрывается, а перед повтором — дочитывается.
- [ ] Каждый запрос имеет идентификатор, он есть и в логах, и в заголовке ответа.

## Упражнения

1. Добавьте в сервис маршрут `GET /items/{id}` с валидацией: если `id` не число, вернуть 400 с JSON-ошибкой. Проверьте через `curl`, что `POST /items/1` даёт 405 и заголовок `Allow`.
2. Напишите middleware, который ограничивает частоту запросов с одного IP до 10 в секунду ({{L|g119|token bucket}} на `time.Ticker`), и проверьте его `hey` или простым циклом в `curl`.
3. Реализуйте клиент с повторами и джиттером, затем протестируйте его против локального сервера, который отвечает 503 первые два запроса. Убедитесь по логам, что задержки растут.
4. Запустите сервис под нагрузкой, отправьте `SIGTERM` в момент активных запросов и убедитесь, что все они завершились успешно. Затем поставьте `WriteTimeout` в 100 мс и повторите — объясните результат.
5. Подключите `net/http/pprof` на отдельный порт (не на публичный мультиплексор) и снимите профиль горутин под нагрузкой. Найдите, сколько горутин занято обработкой запросов и сколько ждёт в `select`.

*Ответы и разбор к этим упражнениям — в приложении D, часть 4.*
