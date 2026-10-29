# Глава 34. Базы данных в Go

Проблемы в продакшене Go-сервиса почти всегда приходят из базы: «слишком много соединений», «запрос висит двадцать минут», «после переключения на реплику всё сломалось». В главе разбирается `database/sql`: почему это не драйвер, а пул с неочевидными дефолтами. Дальше — `context` в каждом запросе, защита от инъекций, миграции и деградация при недоступной базе.

## database/sql: что это на самом деле

`database/sql` — не драйвер и не ORM. Это прослойка: единый интерфейс (`QueryContext`, `ExecContext`, `BeginTx`), пул соединений, кэш подготовленных выражений. Протокол реализует драйвер, который регистрируется в `init()` и подключается пустым импортом:

```go
import (
	"database/sql"

	_ "github.com/jackc/pgx/v5/stdlib" // регистрирует драйвер "pgx"
)
```

Для PostgreSQL разумен `jackc/pgx/v5/stdlib` (`lib/pq` — в режиме поддержки), для SQLite — `modernc.org/sqlite`, чистый Go без cgo: важно для статических бинарников (глава 36).

Главное следствие: `*sql.DB` — это **пул**, а не соединение. Он создаётся один раз на процесс и передаётся в репозитории. `sql.Open` не устанавливает соединение — только разбирает DSN, поэтому ошибка в пароле проявится на первом запросе, а не при старте.

```go
func openDB(ctx context.Context, dsn string) (*sql.DB, error) {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}
	db.SetMaxOpenConns(20)
	db.SetMaxIdleConns(20)
	db.SetConnMaxLifetime(30 * time.Minute)
	db.SetConnMaxIdleTime(5 * time.Minute)

	pingCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	if err := db.PingContext(pingCtx); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping db: %w", err)
	}
	return db, nil
}
```

## Пул соединений и почему дефолты опасны

| Параметр | Дефолт | Что это значит |
|---|---|---|
| `MaxOpenConns` | 0 (без лимита) | Число соединений ограничено только нагрузкой |
| `MaxIdleConns` | 2 | В пуле простаивает максимум два соединения |
| `ConnMaxLifetime` | 0 (вечно) | Соединение живёт до закрытия процесса |
| `ConnMaxIdleTime` | 0 (вечно) | Простаивающее соединение не закрывается |

Неограниченный `MaxOpenConns` — первая мина. PostgreSQL по умолчанию принимает 100 клиентских соединений, и каждый бэкенд — процесс ОС. Двадцать подов под всплеском легко дают две тысячи соединений, и база отвечает `FATAL: sorry, too many clients already`, причём отказывает и старым подам.

`MaxIdleConns = 2` при `MaxOpenConns = 20` — вторая. На всплеске открывается двадцать соединений, после спада восемнадцать закрываются, на следующем всплеске снова открываются. Каждое новое — TCP-хендшейк, TLS, аутентификация и `fork` бэкенда: миллисекунды, которые складываются в задержку. `MaxIdleConns` ставят равным `MaxOpenConns`.

Бесконечный `ConnMaxLifetime` — третья. Соединение может прожить сутки; за это время pgbouncer или балансировщик закроет его по таймауту простоя, и приложение получит `unexpected EOF`. При failover соединения смотрят на старый адрес. 15–30 минут гарантируют периодическое пересоздание и повторный резолв DNS.

Бюджет соединений базы делят между всеми экземплярами с запасом на миграции: при 100 соединениях и десяти подах — 8–10 на под.

### Как увидеть, что делает пул

`db.Stats()` отдаёт `Open`, `InUse`, `Idle`, `WaitCount`, `WaitDuration` — их выводят в метрики. Растущий `WaitCount` при `Open == MaxOpenConns` значит, что пул исчерпан и запросы стоят в очереди.

## context в каждом запросе

Нужны `QueryContext`, `QueryRowContext`, `ExecContext`, `BeginTx`, `PingContext`. Версии без контекста означают «ждать вечно»: если база зависла, горутина висит вместе с соединением, двадцать таких исчерпывают пул, и сервис умирает, хотя база жива.

```go
func (s *Store) Order(ctx context.Context, id int64) (*Order, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	row := s.db.QueryRowContext(ctx,
		`SELECT id, user_id, total_cents, status, created_at
		   FROM orders WHERE id = $1`, id)

	var o Order
	err := row.Scan(&o.ID, &o.UserID, &o.TotalCents, &o.Status, &o.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("query order %d: %w", id, err)
	}
	return &o, nil
}
```

Таймаут ограничивает время удержания соединения и берётся из бюджета запроса (глава 33). Для `Query` обязателен `defer rows.Close()`: незакрытые строки держат соединение.

## Prepared statements и SQL-инъекции

Склейка SQL строками — самый распространённый способ получить инъекцию:

```go
q := fmt.Sprintf("SELECT id FROM users WHERE email = '%s'", email)
// email = "x@y.z' OR '1'='1"  → вернёт всех пользователей
```

Правильно — плейсхолдер: драйвер отправляет запрос и значения отдельно, поэтому значение не может стать частью SQL.

```go
row := db.QueryRowContext(ctx, `SELECT id FROM users WHERE email = $1`, email)
```

Синтаксис зависит от драйвера: `$1, $2` в PostgreSQL, `?` в MySQL и SQLite; `database/sql` их не переводит. Плейсхолдер работает только для **значений**: `$1` на месте имени колонки PostgreSQL не примет, поэтому динамическая сортировка идёт через белый список:

```go
col, ok := map[string]string{"created": "created_at", "total": "total_cents"}[r.URL.Query().Get("sort")]
if !ok {
	col = "created_at"
}
q := "SELECT id FROM orders ORDER BY " + col + " LIMIT $1"
```

## Транзакции и уровни изоляции

```go
func (s *Store) Transfer(ctx context.Context, from, to, amount int64) error {
	tx, err := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return fmt.Errorf("begin: %w", err)
	}
	defer tx.Rollback() // после Commit вернёт sql.ErrTxDone и ничего не сделает

	if _, err := tx.ExecContext(ctx,
		`UPDATE accounts SET balance = balance - $1 WHERE id = $2`, amount, from); err != nil {
		return fmt.Errorf("debit: %w", err)
	}
	if _, err := tx.ExecContext(ctx,
		`UPDATE accounts SET balance = balance + $1 WHERE id = $2`, amount, to); err != nil {
		return fmt.Errorf("credit: %w", err)
	}
	return tx.Commit()
}
```

`Read Committed` — дефолт PostgreSQL: видны только закоммиченные данные, но между двумя запросами одной транзакции они могут измениться. `Repeatable Read` даёт снимок на всю транзакцию и ловит потерянные обновления ошибкой сериализации. `Serializable` ведёт себя так, будто транзакции шли по очереди, и требует повтора при ошибке `40001`; в MySQL дефолт иной — `Repeatable Read` с next-key блокировками.

## Миграции: goose

Схема версионируется в репозитории и применяется автоматически, а не руками. `pressly/goose/v3` хранит пары Up/Down в SQL-файлах:

```sql
-- migrations/00002_add_orders_status.sql
-- +goose Up
ALTER TABLE orders ADD COLUMN status text NOT NULL DEFAULT 'new';

-- +goose Down
ALTER TABLE orders DROP COLUMN status;
```

Применение из кода — через `embed`, чтобы миграции попали в бинарник:

```go
//go:embed migrations/*.sql
var migrationsFS embed.FS

func Migrate(db *sql.DB) error {
	goose.SetBaseFS(migrationsFS)
	if err := goose.SetDialect("postgres"); err != nil {
		return err
	}
	return goose.Up(db, "migrations")
}
```

Альтернатива — `golang-migrate/migrate/v4` с CLI `migrate -path ./migrations -database "$DSN" up`. Правила: миграции только вперёд; одна миграция — одно изменение; DDL и заполнение данных не смешивать; удаление колонки — отдельным релизом, когда код перестал её читать.

## N+1 и как его увидеть

Код выглядит линейным, а запросов делает N+1:

```go
orders, _ := s.ordersByUser(ctx, userID) // 1 запрос
for _, o := range orders {
	items, _ := s.itemsByOrder(ctx, o.ID) // N запросов
	o.Items = items
}
```

На тысяче заказов это тысяча round-trip по 1–3 мс — секунды и тысяча удержаний соединения. Лечится `JOIN` или двумя запросами с массивом:

```go
rows, err := s.db.QueryContext(ctx,
	`SELECT order_id, sku, qty FROM order_items WHERE order_id = ANY($1)`, ids)
```

Увидеть N+1 можно счётчиком запросов в middleware (обёртка над `*sql.DB` логирует HTTP-вызовы, где запросов больше пяти), через `pg_stat_statements` или по трассировке с десятками одинаковых спанов `SELECT`.

## Healthcheck и деградация

Проверка базы не должна быть дорогой. `PingContext` с таймаутом 1–2 секунды — для readiness: под выводится из балансировки, но не перезапускается. В liveness проверку базы не ставят, иначе Kubernetes перезапустит здоровые поды и устроит шторм.

```go
func (h *Health) Ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 1500*time.Millisecond)
	defer cancel()
	if err := h.db.PingContext(ctx); err != nil {
		http.Error(w, "db unavailable", http.StatusServiceUnavailable)
		return
	}
	w.WriteHeader(http.StatusOK)
}
```

Деградация — это поведение, когда база не отвечает: таймауты на всё, ограниченные ретраи с backoff, ответ 503 с `Retry-After` вместо зависшего запроса. Для критичных зависимостей добавляют {{L|g15|circuit breaker}}: после серии ошибок запросы не отправляются вовсе, и база не захлёбывается ретраями.

## Типичные ошибки

1. **`sql.Open` без настройки пула.** Дефолты дают неограниченные соединения и вечный `ConnMaxLifetime`; проблема проявляется не на тесте, а на сотнях RPS.
2. **Новый `*sql.DB` в хендлере.** Каждый `Open` создаёт свой пул, соединения не переиспользуются.
3. **`db.Query` вместо `QueryContext`.** Бесконечное ожидание и удержание соединения: при зависании базы пул выедается.
4. **Забытый `rows.Close()`.** `Query` держит соединение, пока строки не прочитаны или не закрыты.
5. **Склейка SQL через `fmt.Sprintf`.** Любое пользовательское значение в тексте запроса — потенциальная инъекция.
6. **Проверка базы в liveness.** При недоступности базы перезапускаются все поды сразу; восстановление превращается в шторм.
7. **Миграции вручную и без версий.** Окружения расходятся, и никто не знает, какая схема на проде.

## Чек-лист

- [ ] `MaxOpenConns` задан числом из бюджета соединений базы, а не нулём.
- [ ] `MaxIdleConns` равен `MaxOpenConns`, `ConnMaxLifetime` — 15–30 минут.
- [ ] `PingContext` с таймаутом вызывается при старте, сервис не поднимается при ошибке.
- [ ] Все запросы идут через `*Context`-методы, у каждого есть таймаут.
- [ ] `rows.Close()` стоит в `defer` сразу после успешного `Query`.
- [ ] Значения передаются плейсхолдерами, идентификаторы — из белого списка.
- [ ] В транзакции есть `defer tx.Rollback()`.
- [ ] Есть `/readyz` с проверкой базы и метрики `db.Stats()` в мониторинге.

## Упражнения

1. Запустите PostgreSQL с `max_connections=20` и сервис с `MaxOpenConns=0` под 200 параллельными запросами. Поймайте «too many clients» и почините конфигурацией пула.
2. Напишите обёртку над `*sql.DB`, считающую запросы на HTTP-вызов, найдите N+1 и перепишите его на `ANY($1)`.
3. Реализуйте `Transfer` с `LevelSerializable` и тремя повторами при ошибке `40001` с jitter; проверьте под нагрузкой, что баланс не уходит в минус.
4. Добавьте миграции на goose: колонку `status`, индекс по `user_id`, удаление старой колонки; прогоните `up`, `down`, `up`.
5. Сделайте `/readyz` и проверьте поведение при остановленной базе: под должен выйти из балансировки и вернуться в неё без перезапуска.

*Ответы и разбор к этим упражнениям — в приложении D, часть 4.*
