# Глава 37. Git: модель данных, ветки, rebase, хуки

Git изучают с команд — `commit`, `push`, `pull` — и поэтому он кажется набором ритуалов, которые иногда ломаются. На самом деле это маленькая объектная база с четырьмя типами объектов и указателями на них; почти любая «страшная» ситуация сводится к вопросу «на какой коммит сейчас смотрит ссылка». Дальше — модель объектов, merge и {{L|g94|rebase}}, {{L|g95|reflog}}, конфликты и хуки, которые не дают мусору попасть в историю.

## Четыре типа объектов

Содержимое репозитория хранится в `.git/objects` как объекты, адресуемые по хешу содержимого. Типов четыре: **blob** — содержимое файла без имени и прав; **tree** — каталог со списком имён, режимов и хешей; **{{L|g17|commit}}** — tree корня, автор, время, сообщение и родители; **tag** — аннотированная метка с сообщением.

Имя файла живёт в tree, а не в blob, поэтому одинаковое содержимое в двух каталогах — один объект. Внутренности смотрят без рабочих файлов:

```bash
git cat-file -p HEAD
git cat-file -t HEAD
git cat-file -p HEAD^{tree}
git hash-object -w README.md
git rev-parse HEAD
```

```text
tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904
parent 8a1c0f3e2b7d9c4a5e6f708192a3b4c5d6e7f809
author Ivan Petrov <ivan@example.com> 1772000000 +0300
committer Ivan Petrov <ivan@example.com> 1772000100 +0300

Add retry to the HTTP client
```

Хеш — SHA-1 от заголовка объекта и его содержимого; формат выбирается при создании репозитория (`git init --object-format=sha256`), совместимости между форматами нет. Из неизменяемости следует главное: изменить коммит нельзя, можно только создать новый. Вся «правка истории» — создание новых объектов и перестановка указателя.

## Ссылки и HEAD

Ссылка (ref) — файл с хешем коммита: `.git/refs/heads/main`, `.git/refs/tags/v1.4.2`, `.git/refs/remotes/origin/main`. Старые упаковываются в `.git/packed-refs`. `HEAD` — символическая ссылка на текущую ветку:

```bash
cat .git/HEAD
git rev-parse --abbrev-ref HEAD
```

```text
ref: refs/heads/main
main
```

Отсюда «detached HEAD»: если `HEAD` содержит хеш, а не имя ветки, новые коммиты ни к какой ветке не привязаны; `git switch -c hotfix` из этого состояния сохраняет работу. Ветка — указатель, поэтому создание занимает микросекунды.

## merge и rebase

Merge сохраняет обе линии истории и создаёт коммит с двумя родителями; rebase переносит коммиты на новую базу, создавая их заново с другими хешами.

```bash
git switch feature/retry
git merge main          # коммит слияния, если история разошлась
git rebase main         # переписывает коммиты feature поверх main
git log --graph --oneline --decorate --all
```

```text
* 9a0b1c2 (HEAD -> feature/retry) Extract backoff helper
* 5d6e7f8 Add retry to HTTP client
* 3c4d5e6 (main) Bump deps
```

| | merge | rebase |
|---|---|---|
| История | сохраняет ветвление | линейная |
| Хеши коммитов | не меняются | меняются |
| Конфликты | один раз | могут повторяться |
| Общие ветки | безопасен | ломает чужие клоны |

Правило: rebase — для своей локальной ветки до пуша, merge — для интеграции в общую. Переписанная общая ветка означает, что у коллег остались коммиты, которых нет в origin, и `pull` принесёт дубли. `git merge --no-ff` применяют, когда факт слияния ветки нужно сохранить в истории.

## Интерактивный rebase и squash

Перед пушем коммиты приводят в порядок: склеивают «fix typo», переписывают сообщения, разбивают крупное изменение. `git rebase -i HEAD~4` открывает список:

```text
pick 1a2b3c4 Add retry to HTTP client
squash 5d6e7f8 Fix typo
reword 9a0b1c2 Extract backoff helper
drop 3c4d5e6 Debug print
```

`pick` оставляет коммит, `squash` склеивает с предыдущим и открывает редактор общего сообщения, `fixup` склеивает, выбрасывая сообщение, `reword` меняет текст, `edit` останавливает rebase для правки, `drop` удаляет. Ветка переписана и требует `git push --force-with-lease`: он откажется пушить, если в origin появились чужие коммиты, в отличие от `--force`.

## cherry-pick

Бэкпорт хотфикса в релизную ветку:

```bash
git switch release/1.4
git cherry-pick -x 9a0b1c2
```

Флаг `-x` добавляет в сообщение строку `(cherry picked from commit 9a0b1c2)`, и происхождение правки видно через полгода. Cherry-pick создаёт копию с другим хешем: при последующем мерже ветки изменение приедет ещё раз.

## revert вместо reset

`git revert` создаёт новый коммит, отменяющий изменения указанного; `git reset` двигает указатель ветки назад. Это разные операции по смыслу.

```bash
git revert --no-edit 9a0b1c2   # безопасно для запушенной ветки
git reset --soft HEAD~1        # отменить коммит, оставив изменения в индексе
git reset --mixed HEAD~1       # отменить коммит и индекс, файлы целы
git reset --hard HEAD~1        # выбросить коммит И правки в рабочих файлах
```

`--hard` опасен тем, что удаляет незакоммиченные правки без возможности восстановления: reflog хранит коммиты, но не содержимое каталога.

```bash
git stash push -m wip
git reset --hard HEAD~1
git stash pop
```

На общей ветке `reset` запрещён: у остальных останутся «удалённые» коммиты, и следующий push вернёт их.

## reflog как спасение

Reflog — локальный журнал перемещений `HEAD` и веток: 90 дней для достижимых коммитов, 30 для недостижимых.

```bash
git reflog
git log -g --oneline -n 5
```

```text
9a0b1c2 HEAD@{0}: reset: moving to HEAD~1
1a2b3c4 HEAD@{1}: commit: Add retry to HTTP client
5d6e7f8 HEAD@{2}: checkout: moving from main to feature/retry
```

```bash
git reset --hard HEAD@{1}
```

Этого хватает для большинства случаев «я всё потерял»: неудачный rebase, `reset --hard`, удалённая ветка. Если коммит не виден в reflog, работает `git fsck --lost-found`:

```bash
git fsck --lost-found
git show --stat 3c4d5e6
git branch --contains 9a0b1c2
```

```text
dangling commit 3c4d5e6b7a8f9e0d1c2b3a4f5e6d7c8b9a0f1e2d
```

Найденный хеш открывают через `git show` и возвращают в ветку `git branch rescue 3c4d5e6`.

## Конфликты и их разрешение

Конфликт возникает, когда обе стороны изменили одни и те же строки. Git оставляет маркеры в файле:

```text
<<<<<<< HEAD
timeout: 5 * time.Second
=======
timeout: 10 * time.Second
>>>>>>> feature/retry
```

```bash
git status --short
git diff --name-only --diff-filter=U
git log --merge --oneline -p
```

```text
interactive rebase in progress; onto 3c4d5e6
You are currently rebasing branch 'feature/retry' on '3c4d5e6'.
  (fix conflicts and then run "git rebase --continue")

UU internal/client/client.go
```

`UU` значит «изменён обеими сторонами». После правки — `git add` и продолжение: `git rebase --continue` или `git merge --continue`. Полезны `git checkout --ours` / `--theirs` (взять сторону целиком) и `git rerere` — он запоминает разрешения и применяет их повторно при rebase той же ветки.

## Хуки

Хуки — исполняемые скрипты, которые git вызывает на события. Каталог `.git/hooks` не клонируется, поэтому команда либо раскладывает хуки установочным скриптом, либо задаёт общий путь:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/*
git config --get core.hooksPath
```

`.githooks/pre-commit` не даёт закоммитить неотформатированный Go:

```bash
#!/bin/sh
set -e
files=$(git diff --cached --name-only --diff-filter=ACM | grep '\.go$' || true)
[ -z "$files" ] && exit 0
unformatted=$(gofmt -l $files)
if [ -n "$unformatted" ]; then
    echo "gofmt required for:"
    echo "$unformatted"
    exit 1
fi
go vet ./...
```

`.githooks/commit-msg` требует номер задачи в первой строке:

```bash
#!/bin/sh
head -1 "$1" | grep -qE '^[A-Z]+-[0-9]+: .+' || {
    echo "commit message must look like: API-142: add retry"
    exit 1
}
```

Хуки обходятся флагом `--no-verify`, поэтому они не заменяют CI, а экономят время: ошибка видна до пуша.

## .gitignore и секреты в истории

`.gitignore` действует только на неотслеживаемые файлы. Если `.env` уже закоммичен, правило ничего не изменит: файл убирают из индекса (`git rm --cached .env`) и коммитят удаление. История при этом сохранит содержимое, и любой, кто клонирует репозиторий, получит секрет.

```bash
git log --all -p -S 'AKIA' --oneline
git log --all --diff-filter=D --name-only -- '*.env'
```

Если утечка подтверждена: сначала ротация ключа, затем вычистка истории (`git filter-repo --path .env --invert-paths` или BFG), форс-пушнуть и попросить коллег переклонировать. Вычистка без ротации бессмысленна: ключ уже был в чужом клоне, в бэкапе и в логах CI.

## Типичный рабочий цикл

```bash
git switch main
git pull --ff-only
git switch -c feature/retry
git status --short
git add -p                 # по кускам, а не всё подряд
git commit -m "API-142: add retry with backoff to HTTP client"
git fetch origin
git rebase origin/main
go test ./... && go vet ./...
git push -u origin feature/retry
git push --force-with-lease
```

`pull --ff-only` не создаёт коммит слияния в локальной main и сразу сообщает о расхождении. `add -p` даёт осмысленные коммиты, а `rebase origin/main` перед пушем делает Pull Request линейным.

## Типичные ошибки

1. **`git reset --hard` без сохранения работы.** Reflog восстанавливает коммиты, но не незакоммиченные правки — они теряются навсегда.
2. **Rebase запушенной общей ветки.** Хеши меняются, у коллег остаются осиротевшие коммиты, следующий `pull` приносит дубли.
3. **`push --force` вместо `--force-with-lease`.** Флаг без lease затирает чужие коммиты, появившиеся в origin после вашего fetch.
4. **Секрет в истории.** `.gitignore` не удаляет уже отслеживаемый файл, а вычистка без ротации ключа ничего не даёт.
5. **Хуки только локально.** `.git/hooks` не клонируется, у нового разработчика проверок нет — нужен `core.hooksPath`.
6. **`git add .` в спешке.** В коммит попадают отладочные файлы и локальные конфиги; `add -p` дешевле разбора.
7. **Merge-коммиты на общей ветке по умолчанию.** История заполняется «Merge {{L|g8|branch}} main», и найти причину изменения труднее.

## Чек-лист

- [ ] `git config core.hooksPath` указывает на версионируемый каталог с хуками.
- [ ] Хуки `pre-commit` и `commit-msg` исполняемые и проверены на `--no-verify`.
- [ ] В `.gitignore` есть `.env`, `bin/`, локальные конфиги; отслеживаемые секреты убраны из индекса.
- [ ] Force-push только через `--force-with-lease`.
- [ ] В shared-ветках нет rebase и `reset`.
- [ ] Сообщения коммитов содержат номер задачи, squash перед PR выполнен.
- [ ] `git log --all -S` по паттернам ключей не находит утечек.
- [ ] Pull Request — линейная ветка, `go test` и `go vet` зелёные до пуша.

## Упражнения

1. Создайте коммит, посмотрите `git cat-file -p HEAD` и `HEAD^{tree}`; убедитесь, что `git hash-object` того же содержимого даёт тот же хеш.
2. Сделайте ветку с тремя коммитами, склейте их через `git rebase -i`, затем верните исходное состояние через `git reflog`.
3. Смоделируйте конфликт в двух ветках, разрешите его, включите `git rerere` и повторите rebase — конфликт должен разрешиться автоматически.
4. Напишите `pre-commit` с проверкой `gofmt` и `commit-msg` с номером задачи; проверьте обход через `--no-verify`.
5. Заведите коммит с фальшивым ключом, найдите его через `git log -S`, вычистите `git filter-repo` и проверьте, что объект исчез.

*Ответы и разбор к этим упражнениям — в приложении D, часть 4.*
