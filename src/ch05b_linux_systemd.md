# Глава 5b. Linux: пакеты, systemd, журналы

Сервер живёт не сам по себе: сотня пакетов, десятки юнитов, гигабайты логов. Три навыка покрывают почти всю работу с этим хозяйством — откуда взялся файл и какая у него версия; как описать сервис, чтобы он перезапускался сам и не висел под root; как найти в журнале момент, когда всё сломалось. Ниже — apt и dpkg, unit-файлы {{L|g115|systemd}} целиком, {{L|g57|journald}} и logrotate, и рабочий юнит с таймером для ночного бэкапа. Примеры на Debian 13 (systemd 257); отличия RHEL отмечены, где меняют практику.

## Пакеты: репозитории, приоритеты, зависимости

Пакет — архив с файлами плюс метаданные: имя, версия, зависимости, контрольные суммы, скрипты установки. Apt держит локальную базу (`/var/lib/dpkg`) и индексы репозиториев из `/etc/apt/sources.list` и `/etc/apt/sources.list.d/`; в Debian 13 и Ubuntu 24.04 преобладает формат deb822 — файл `*.sources` с полями `Types`, `URIs`, `Suites`, `Components`.

```bash
apt-cache policy nginx
```

```
nginx:
  Installed: (none)
  Candidate: 1.26.3-3+deb13u10
  Version table:
     1.26.3-3+deb13u10 500
        500 http://security.debian.org/debian-security trixie-security/main amd64 Packages
     1.26.3-3+deb13u7 500
        500 http://deb.debian.org/debian trixie/main amd64 Packages
```

Число после версии — приоритет (pin priority). `500` — обычный репозиторий, `100` — установленный пакет или архив без явной политики, `990` — обычно backports, `1000` и выше — версия, закреплённая вручную. Итоговый кандидат выбирается по формуле: приоритет, затем версия. Политику задают в `/etc/apt/preferences.d/`:

```
Package: nginx
Pin: version 1.26.3-3+deb13u7
Pin-Priority: 1001
```

Это и есть «пин» — способ не пустить в продакшн версию, пока её не проверили. Обратная сторона: запиненный пакет перестаёт получать исправления безопасности.

Зависимости разрешает apt: `Depends` (без пакета нельзя), `Recommends` (ставится по умолчанию, отключается `--no-install-recommends`), `Suggests` (не ставится). Когда граф не сходится, apt предлагает варианты — и слепо соглашаться на «remove 40 packages» не стоит. В RHEL то же делают `dnf repoquery --requires`, приоритеты задаёт `priority=` в `.repo`, а версии фиксирует `versionlock`.

## Версии, владельцы файлов и hold

```bash
apt list --installed 2>/dev/null | head -3
```

```
Listing...
7zip/stable,now 25.01+dfsg-1~deb13u2 amd64 [installed,automatic]
adduser/stable,now 3.152 all [installed]
```

Пометка `automatic` означает, что пакет притянут зависимостью и уйдёт `apt autoremove`, когда станет не нужен; `apt-mark manual nginx` говорит «поставлен осознанно».

Главный инструмент — «какой пакет владеет файлом»:

```bash
dpkg -S /usr/bin/ls
dpkg -L coreutils | head -3
```

```
coreutils: /usr/bin/ls
/.
/usr
/usr/bin
```

Если файл не принадлежит ни одному пакету, `dpkg -S` ответит `no path found` — сигнал, что он собран вручную и потеряется при переустановке. Для файлов из неустановленных пакетов — `apt-file search`, в RHEL — `dnf provides */nginx.conf` и `rpm -qf /etc/nginx/nginx.conf`.

Версии держат `apt-mark hold nginx` (снять — `unhold`), в RHEL — `dnf versionlock add nginx`. Hold — мера на время инцидента, не стратегия: без обновлений пакет копит уязвимости.

## Обновления: upgrade, full-upgrade и цена спешки

```bash
apt update            # обновить индексы, не трогая пакеты
apt upgrade           # обновить всё, что можно без удаления пакетов
apt full-upgrade      # разрешить удаление и установку ради зависимостей
```

Разница принципиальна. `apt upgrade` не удаляет пакеты: если новая версия требует убрать зависимость, пакет останется старым. `apt full-upgrade` (ранее `dist-upgrade`) удаляет и добавляет что угодно ради консистентного графа — он и сносит половину системы, если подключён сторонний репозиторий с другой libc. Порядок: `apt update && apt upgrade`, глазами `apt list --upgradable`, и только потом `full-upgrade` с чтением списка `REMOVING`.

В Debian автообновления безопасности делает `unattended-upgrades`, в RHEL — `dnf-automatic`. Полезен и `needrestart` (`dnf needs-restarting`): обновление библиотеки не меняет уже запущенный процесс — сервис работает со старой версией в памяти, пока его не перезапустят.

## Unit-файлы: три секции

Юнит — текстовое описание объекта для systemd. Каталоги поиска по убыванию приоритета: `/etc/systemd/system` (администратор), `/run/systemd/system` (временные), `/usr/lib/systemd/system` (пакеты). Файл с тем же именем в `/etc` перекрывает пакетный целиком; `systemctl edit` создаёт drop-in `name.service.d/override.conf` — правильный способ правки чужого юнита.

```ini
[Unit]
Description=Example API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=app
Group=app
WorkingDirectory=/srv/app
Environment=APP_ENV=production
EnvironmentFile=/etc/app/env
ExecStart=/srv/app/bin/api --listen :8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`[Unit]` — метаданные и зависимости, `[Service]` — как запускать и что делать при падении, `[Install]` — при какой цели включать (`WantedBy` создаёт ссылку в `/etc/systemd/system/multi-user.target.wants/` при `systemctl enable`). Без `[Install]` юнит запускается только вручную или по зависимости.

## Типы сервисов: simple, oneshot, notify

`Type=` определяет, когда systemd считает сервис запущенным.

| Тип | Когда «запущен» | Для чего |
|---|---|---|
| `simple` (по умолчанию) | сразу после `fork/exec` | обычные демоны, не сообщающие о готовности |
| `exec` | после успешного `execve` | когда важен провал запуска (нет файла, нет прав) |
| `oneshot` | после завершения процесса | скрипты, задачи; нужен `RemainAfterExit=yes`, если сервис «активен» после выхода |
| `notify` | после `sd_notify(READY=1)` | приложения с поддержкой systemd (Go, Python через sdnotify) |
| `forking` | после выхода родителя | старые демоны, демонизирующиеся сами |

Разница видна на практике: `Type=simple` с битым `ExecStart` даёт `active (running)`, а через секунду — `failed`, и в мониторинге это «моргание». `Type=exec` поймает отсутствующий бинарник сразу. `Type=notify` убирает гонку «порт ещё не слушается, а systemd уже говорит „готово“».

## Падения, лимиты и окружение

`Restart=on-failure` перезапускает при ненулевом коде выхода, сигнале или таймауте; `always` — и после чистого выхода. `RestartSec=` по умолчанию 100 мс, и это почти всегда слишком быстро: падающий на старте сервис крутится в tight loop. После `StartLimitBurst` попыток за `StartLimitIntervalSec` (по умолчанию 5 за 10 секунд) systemd сдаётся и пишет `start request repeated too quickly` — сбросить счётчик можно `systemctl reset-failed`.

Остальное, что чаще всего правят:

- `User=`/`Group=` — под кем работать; без них сервис работает под root, и это главная ошибка самописных юнитов;
- `Environment=` — переменные в юните (строка `KEY=VALUE`), `EnvironmentFile=` — файл с правами `600`; префикс `-` разрешает его отсутствие. Синтаксис не shell: никаких `export`, кавычек и подстановок;
- `LimitNOFILE=` — лимит дескрипторов; в юнитах по умолчанию 1024, и для сервиса с тысячами соединений это «слишком много открытых файлов» в самый неподходящий момент. `LimitNOFILE=65536` — обычная практика;
- `UMask=` — маска создания файлов (глава 5a): сервис наследует маску демона, а не вашей оболочки;
- `TimeoutStopSec=` (по умолчанию 90 с) — сколько ждать корректной остановки перед `SIGKILL`; сервис, игнорирующий `SIGTERM`, будет убит жёстко и потеряет незаписанные данные;
- `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectSystem=strict`, `ReadWritePaths=` — песочница без контейнера: с `strict` ФС только для чтения, запись разрешают точечно.

## Зависимости: After, Wants, Requires

Порядок и необходимость — разные вещи, и их путают чаще всего:

- `Wants=` — «запусти вместе со мной, но если он упал, мне всё равно»;
- `Requires=` — «без него нельзя»: падение зависимости останавливает и юнит;
- `After=`/`Before=` — только порядок, без требования запускать;
- `BindsTo=` — жёстче `Requires`: остановка зависимости останавливает юнит;
- `PartOf=` — остановка/перезапуск распространяется в обратную сторону.

`Wants=network-online.target` без `After=network-online.target` не даёт ничего, кроме «цель тоже будет запущена»: сервис стартует параллельно и, возможно, раньше сети. Нужны оба. `After=network.target` — «стек инициализирован», а не «есть адрес и маршрут»; реальную готовность даёт `network-online.target`.

После правки любого юнита — `systemctl daemon-reload`: без него systemd работает со старым описанием, и «изменения не применились» — забытая команда. Перезагрузка нужна и после изменения `[Install]`, но не после правки `EnvironmentFile`: файл читается при каждом старте.

## Таймеры вместо cron

Таймер — юнит `.timer` рядом с `.service` того же имени. Выигрыш перед cron: логи в journald, зависимости и песочница как у сервиса, `Persistent=true` — догоняющая работа после простоя машины.

```ini
[Unit]
Description=Nightly backup

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
RandomizedDelaySec=10min
AccuracySec=1min
Unit=backup.service

[Install]
WantedBy=timers.target
```

`OnCalendar` понимает `daily`, `Mon..Fri 09:00` и полный формат `год-месяц-день часы:минуты:секунды`; `systemd-analyze calendar '*-*-* 03:30:00'` печатает нормализованную форму и следующие срабатывания. `Persistent=true` хранит отметку запуска в `/var/lib/systemd/timers` и догоняет пропущенное после загрузки. `RandomizedDelaySec` разводит сотню машин, чтобы они не пришли на бэкап-сервер одной секундой.

```bash
systemctl enable --now backup.timer
systemctl list-timers backup.timer
```

```
NEXT                        LEFT     LAST                        PASSED  UNIT          ACTIVATES
Fri 2026-10-30 03:30:00 +05 7h 31min Thu 2026-10-29 03:31:12 +05 16h ago backup.timer  backup.service
```

`enable` нужен таймеру, а не сервису: `[Install]` в юните сервиса заставит его запускаться ещё и при загрузке.

## journald и journalctl

systemd собирает stdout/stderr сервисов, ядро и syslog в один бинарный журнал:

```bash
journalctl -u backup.service --since today      # по юниту и времени
journalctl -u docker.service -f                 # следить в реальном времени
journalctl -b -1 -p err                         # прошлая загрузка, только ошибки
journalctl --since "2026-10-29 03:00" --until "2026-10-29 04:00" -o short-iso
journalctl -u app.service -o json-pretty | head -40
journalctl --disk-usage
```

```
окт 29 03:30:02 nextpc backup[2417]: dumping pg: 128 MB in 4.1s
окт 29 03:30:06 nextpc backup[2417]: upload: 1.2 GB in 3.9s
```

Приоритеты — от `0` (emerg) до `7` (debug); `-p err` — «err и выше», `-p warning..err` — диапазон. `-b -1` — предыдущая загрузка, `--list-boots` покажет все. Фильтры по полям: `_PID=2417`, `_SYSTEMD_UNIT=`.

По умолчанию `Storage=auto`, и журнал **не переживает перезагрузку**: он в `/run`, пока нет каталога `/var/log/journal`. `mkdir /var/log/journal && systemctl restart systemd-journald` делает его постоянным. Размер задают в `/etc/systemd/journald.conf` (`SystemMaxUse=2G`), чистят `journalctl --vacuum-size=500M`.

## Ротация: logrotate

Если сервис пишет в файл сам, journald ему не указ — нужен logrotate. Конфиг в `/etc/logrotate.d/`, проверка без изменений — `logrotate -d`.

```
/var/log/app/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 app adm
    sharedscripts
    postrotate
        systemctl reload app.service >/dev/null 2>&1 || true
    endscript
}
```

`rotate 14` — хранить 14 архивов, `delaycompress` — не сжимать самый свежий (его ещё может держать процесс), `create` задаёт права нового файла. `postrotate` обязателен, если процесс держит дескриптор: без переоткрытия он продолжит писать в переименованный файл, и диск забьётся «удалённым» логом. Альтернатива `copytruncate` теряет строки при копировании. На Debian logrotate запускается таймером.

## systemd-analyze blame

```bash
systemd-analyze blame | head -4
systemd-analyze critical-chain multi-user.target
```

```
2min 9.094s backup-weekly.service
    42.396s health-check.service
     5.405s systemd-modules-load.service
     2.477s gpu-setup.service
```

`blame` показывает время активации юнитов, а не «тормоза загрузки»: `Type=oneshot` с двухминутным скриптом законно занимает две минуты и попадает в топ, хотя загрузку не задерживает, если от него никто не зависит. Реальное время определяет `critical-chain`.

## Полный рабочий пример: бэкап по таймеру

Скрипт `/usr/local/bin/backup.sh` (проверка места, дамп, rsync) и два юнита.

```ini
# /etc/systemd/system/backup.service
[Unit]
Description=Nightly backup of /srv/app to /mnt/backup
RequiresMountsFor=/mnt/backup
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=backup
Group=backup
EnvironmentFile=/etc/backup.env
ExecStart=/usr/local/bin/backup.sh --src /srv/app --dst /mnt/backup
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
TimeoutStartSec=2h
UMask=0027
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/mnt/backup
NoNewPrivileges=yes
```

```ini
# /etc/systemd/system/backup.timer
[Unit]
Description=Run nightly backup at 03:30

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
RandomizedDelaySec=10min
Unit=backup.service

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/backup.service
systemctl start backup.service
systemctl enable --now backup.timer
journalctl -u backup.service -n 20 --no-pager
```

Разбор решений: `Type=oneshot` — скрипт завершается, сервис не «висит»; `RequiresMountsFor` гарантирует, что `/mnt/backup` смонтирован, иначе бэкап уйдёт в корневую ФС; `TimeoutStartSec=2h` — дефолтных 90 секунд не хватит; `Nice` и `IOSchedulingClass` снижают давление на диск. `systemd-analyze verify` ловит опечатки в путях до первого запуска.

## Типичные ошибки

1. **Правка юнита без `daemon-reload`.** Изменения не применяются, в статусе старый `ExecStart`: systemd держит разобранные юниты в памяти.
2. **`Wants=` без `After=`.** Зависимость запускается, но порядок не гарантирован — падение на гонке «сети ещё нет»: `Wants` — необходимость, `After` — порядок.
3. **Сервис под root по умолчанию.** Нет `User=` — демон получает полные права; systemd не наследует пользователя из вашей оболочки.
4. **`LimitNOFILE=1024`.** Сервис упирается в дескрипторы при росте соединений: это дефолт юнита, а не хоста, и `ulimit -n` в сессии о сервисе ничего не говорит.
5. **`Type=simple` для скрипта.** `systemctl start` возвращает успех, хотя скрипт уже упал: «запущен» значит «процесс создан», а не «работает».
6. **`apt full-upgrade` без чтения списка удалений.** При сторонних репозиториях сносит нужные пакеты: `full-upgrade` разрешает удаление ради консистентности графа.

## Чек-лист

- `dpkg -S $(command -v nginx)` отвечает, какой пакет владеет бинарником; `dpkg -V пакет` не показывает изменённых файлов.
- `apt upgrade` выполняется регулярно, `full-upgrade` — осознанно, с чтением `REMOVING`.
- У каждого самописного юнита есть `[Install]`, `User=`, `Restart=`, `RestartSec≥1s`.
- `systemd-analyze verify` проходит для всех новых юнитов, таймер включён, а сервис — нет.
- `/var/log/journal` существует, `SystemMaxUse` задан; для файловых логов есть конфиг в `/etc/logrotate.d/` с `postrotate`.

## Упражнения

1. Найдите пакет, которому принадлежит `/usr/bin/ss`, и все файлы этого пакета. Объясните, что означает `ii` в `dpkg -l`.
2. Запинните nginx на текущую версию, обновите индексы и докажите, что кандидат не изменился. Затем снимите пин и объясните риск.
3. Напишите юнит для Python-сервиса с `Type=notify`, ограничением `LimitNOFILE=65536` и песочницей, проверьте его `systemd-analyze verify`.
4. Сделайте таймер для healthcheck каждые 5 минут так, чтобы пропущенный запуск выполнился после перезагрузки.
5. Ограничьте журнал 500 МБ, включите постоянное хранение и найдите все ошибки предыдущей загрузки одной командой.

*Ответы и разбор к этим упражнениям — в приложении D, часть 1.*
