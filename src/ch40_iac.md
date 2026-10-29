# Глава 40. IaC: Terraform и Ansible

Инфраструктура, собранная руками в консоли облака, существует в единственном экземпляре и только в памяти того, кто её собирал. Воспроизвести её в другом регионе нельзя, откатить изменение нечем, а причина ночного инцидента выясняется сравнением скриншотов. Infrastructure as Code (IaC) переносит описание инфраструктуры в файлы, которые лежат в git, проходят ревью и применяются автоматически. В главе два инструмента с разной природой: Terraform описывает, какие ресурсы должны существовать, Ansible — каким должно быть состояние машин. После главы вы сможете написать конфигурацию с remote state и блокировками, playbook с handlers и шаблонами и объяснить, почему `plan` в CI важнее, чем `apply` на ноутбуке.

## Декларативный и императивный подход

Императивный подход отвечает на вопрос «что делать»: создать каталог, если его нет, установить пакет, запустить сервис. Скрипт из десяти команд ломается на второй, если каталог уже существует.

Декларативный подход отвечает на вопрос «что должно быть»: три виртуальные машины такого типа, такой server-блок в конфиге nginx, установленный пакет. Инструмент сам вычисляет разницу между желаемым и текущим и выполняет недостающее.

Terraform декларативен по отношению к набору ресурсов: он строит граф зависимостей и создаёт недостающее. Ansible формально тоже декларативен, но применяется последовательно по машинам и задачам, поэтому в нём легко скатиться к императивному сценарию из `command` и `shell`.

| | Terraform | Ansible |
|---|---|---|
| Модель | желаемый набор ресурсов | желаемое состояние хостов |
| Область | облако, сеть, DNS, кластеры | ОС, пакеты, конфиги, деплой |
| Состояние | хранит state-файл | без состояния, опрашивает хост |
| Порядок | граф зависимостей | порядок задач в playbook |
| Агент на хосте | не нужен | не нужен (SSH) |

## Terraform: провайдеры, ресурсы, state

Конфигурация Terraform состоит из блоков: `terraform` (версии и backend), `provider` (плагин, который умеет говорить с API), `resource` (объект, которым управляем), `variable`, `local`, `output`, `module`.

```hcl
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  backend "s3" {
    bucket         = "shop-tfstate"
    key            = "prod/storage/terraform.tfstate"
    region         = "eu-central-1"
    dynamodb_table = "tf-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = "eu-central-1"
  default_tags {
    tags = local.tags
  }
}

variable "environment" {
  type        = string
  description = "Имя окружения"
  validation {
    condition     = contains(["dev", "stage", "prod"], var.environment)
    error_message = "Допустимы только dev, stage и prod."
  }
}

variable "vpc_id" {
  type = string
}

locals {
  name = "shop-${var.environment}"
  tags = {
    Project     = "shop"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket" "uploads" {
  bucket = "${local.name}-uploads"
  tags   = local.tags
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_security_group" "api" {
  name        = "${local.name}-api"
  description = "HTTPS для API"
  vpc_id      = var.vpc_id
  tags        = local.tags

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

output "uploads_bucket" {
  value       = aws_s3_bucket.uploads.bucket
  description = "Имя бакета для загрузок"
}
```

Здесь важно несколько вещей. `required_providers` фиксирует диапазон `~> 6.0`: патчи приезжают, мажорные изменения — нет. `default_tags` избавляет от копирования тегов в каждый ресурс — без тегов через полгода не понять, за что платит счёт. `validation` ловит опечатку `prd` на этапе `plan`. `aws_s3_bucket_public_access_block` вынесен отдельным ресурсом намеренно: так видно, что именно меняется.

### State: что это и почему его не хранят в git

State — JSON-файл с соответствием между адресами в конфигурации (`aws_s3_bucket.uploads`) и реальными идентификаторами в облаке. Без state Terraform не знает, что бакет уже создан, и попытается создать второй.

В state попадают все атрибуты, включая чувствительные: пароли баз, приватные ключи, строки подключения. Это первая причина не коммитить его. Вторая — конкурентность: два инженера с разными копиями применят изменения независимо, один затрёт состояние другого, и Terraform «потеряет» ресурсы, создав дубликаты. Третья — конфликты слияния, которые невозможно разрешить осмысленно.

Поэтому state лежит в remote backend: S3 с шифрованием, GCS, Terraform Cloud — с блокировкой на время операции. Блокировка (locking) не даёт двум `apply` идти одновременно. В AWS исторически использовали DynamoDB-таблицу с ключом `LockID`; современные версии умеют блокировку через сам S3, но DynamoDB-вариант всё ещё распространён.

## plan и apply

Рабочий цикл состоит из трёх команд.

```bash
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

`init` скачивает провайдеры и инициализирует backend. `plan` сравнивает конфигурацию, state и реальное состояние облака и показывает, что будет создано (`+`), изменено (`~`) и уничтожено (`-`). `apply tfplan` применяет ровно тот план, который вы видели, — даже если конфигурацию успели поменять.

Читать план нужно целиком, особенно строки с `-`. Случайное удаление выглядит как одна строчка `# aws_db_instance.main will be destroyed`, а последствия — потеря данных. `forces replacement` означает удаление и создание заново: для бакета это потеря содержимого, для балансировщика — смена IP.

Схема в команде: `plan` на каждый pull request с публикацией комментарием, `apply` — только из CI после мержа, с сохранённым артефактом плана.

## Модули

Модуль — переиспользуемый набор ресурсов с входами (`variable`) и выходами (`output`). Модуль вызывается блоком `module`:

```hcl
module "network" {
  source = "../../modules/network"

  name = local.name
  cidr = "10.20.0.0/16"
  azs  = ["eu-central-1a", "eu-central-1b"]
}

module "storage" {
  source      = "../../modules/storage"
  name        = local.name
  environment = var.environment
  vpc_id      = module.network.vpc_id
}
```

Модуль `modules/network` внутри выглядит как обычная конфигурация: `variable "cidr"`, `resource "aws_vpc" "this"`, `output "vpc_id"`. Ссылка `module.network.vpc_id` создаёт неявную зависимость: storage не начнёт создаваться, пока сеть не готова.

Правила, которые делают модули полезными: одна задача и не больше 8–10 входных переменных; не оборачивайте в модуль каждый ресурс — модуль из одного бакета добавляет абстракцию без пользы; версионируйте модули тегом, иначе «последняя версия» сломает прод в чужой день.

## Ansible: инвентарь и playbook

Ansible работает по SSH и не требует агента. Инвентарь (inventory) описывает хосты и группы, playbook — что на них должно быть.

```yaml
all:
  children:
    web:
      hosts:
        web1.example.com:
        web2.example.com:
      vars:
        server_name: shop.example.com
        app_port: 8000
    db:
      hosts:
        db1.example.com:
      vars:
        postgres_version: "17"
```

Playbook — список play, каждый play применяется к группе хостов и состоит из задач.

```yaml
---
- name: Настройка веб-серверов
  hosts: web
  become: true
  vars_files:
    - vars/secrets.yml
  handlers:
    - name: reload nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
  tasks:
    - name: Установить nginx
      ansible.builtin.apt:
        name: nginx
        state: present
        update_cache: true
        cache_valid_time: 3600

    - name: Разложить конфиг виртуального хоста
      ansible.builtin.template:
        src: templates/site.conf.j2
        dest: /etc/nginx/sites-available/shop.conf
        owner: root
        group: root
        mode: "0644"
        validate: nginx -t -c /etc/nginx/nginx.conf
      notify: reload nginx

    - name: Включить сайт
      ansible.builtin.file:
        src: /etc/nginx/sites-available/shop.conf
        dest: /etc/nginx/sites-enabled/shop.conf
        state: link
      notify: reload nginx

    - name: Открыть 443
      community.general.ufw:
        rule: allow
        port: "443"
        proto: tcp

    - name: Создать пользователя деплоя
      ansible.builtin.user:
        name: deploy
        shell: /bin/bash
        groups: www-data
        append: true

    - name: Разрешить деплой-пользователю перезапуск сервиса
      ansible.builtin.copy:
        dest: /etc/sudoers.d/deploy-restart
        content: "deploy ALL=(root) NOPASSWD: /bin/systemctl restart shop\n"
        mode: "0440"
        validate: visudo -cf %s
```

Шаблон `templates/site.conf.j2` — обычный Jinja2 с доступом к переменным инвентаря:

```jinja
server {
    listen 443 ssl;
    server_name {{ server_name }};

    ssl_certificate     /etc/letsencrypt/live/{{ server_name }}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{{ server_name }}/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:{{ app_port }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Идемпотентность модулей

Идемпотентность ({{L|g53|idempotency}}) — свойство операции давать тот же результат при повторном выполнении. `apt` с `state: present` либо ставит пакет, либо сообщает `ok`. `template` сравнивает контрольную сумму и перезаписывает файл, только если содержимое отличается.

Проблема в том, что `command` и `shell` идемпотентными не являются: они выполняются всегда и всегда помечают задачу как `changed`. Лечится это явными условиями:

```yaml
- name: Инициализировать базу приложения
  ansible.builtin.command:
    cmd: /usr/local/bin/shop migrate
    creates: /var/lib/shop/.migrated

- name: Проверить версию
  ansible.builtin.command: /usr/local/bin/shop --version
  register: shop_version
  changed_when: false
  failed_when: shop_version.rc != 0
```

`creates` пропускает задачу, если файл уже существует, — типичный маркер выполненной миграции. `changed_when: false` для проверок, которые ничего не меняют. `failed_when` вместо `ignore_errors`: последний прячет ошибку навсегда, а первый позволяет описать точное условие отказа.

## Handlers и перезапуск сервисов

Handler — задача, которая выполняется один раз, если хотя бы одна задача её уведомила. Так пять изменённых конфигов дают один перезапуск, а не пять. Срабатывают handlers в конце play, поэтому следующая задача увидит ещё старую конфигурацию; если это важно, вызывайте `meta: flush_handlers`.

`validate: nginx -t -c ...` — страховка: сломанный конфиг не попадёт на диск. `visudo -cf %s` для sudoers по той же причине: ошибка в файле лишает root-доступа.

## Vault: секреты в Ansible

Пароли и ключи не должны лежать в git в открытом виде. `ansible-vault` шифрует файл целиком симметричным ключом:

```bash
ansible-vault create vars/secrets.yml
ansible-vault edit vars/secrets.yml
ansible-playbook -i inventory.yml site.yml --ask-vault-pass
```

```yaml
db_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  62313365396662343061393464336163383764373764613633653634306231386433626436623361
  6134333665353966363534333632666535333761666131620a663537646436643839616531643561
  63396265333966386166373632626539326166353965363262633030333630313338646335303630
  3438626666666137650a353638643435666633633964366338633066623234616432373231333331
  6564
```

Ключ передаётся файлом `--vault-password-file` (права `0400`, в git не попадает). Пароль в командной строке виден в истории shell и в `ps`. Задачи с секретами помечаются `no_log: true`, иначе значение попадёт в вывод.

## Когда Terraform, когда Ansible

Граница проходит по жизненному циклу. Terraform управляет сущностями провайдера: VPC, подсети, балансировщики, управляемые базы, DNS-записи, IAM-роли, кластеры Kubernetes. Ansible — состоянием внутри машин: пакеты, файлы, сервисы, пользователи, деплой.

Пересечение — виртуальные машины: Terraform создаёт её и передаёт в Ansible через inventory, конфигурацию внутри делает Ansible. Альтернатива — cloud-init и готовые образы (Packer), тогда Ansible нужен только для деплоя. Признак неверного выбора: `null_resource` с `local-exec`, вызывающий shell-скрипты, — попытка делать конфигурацию инструментом для инфраструктуры. Обратный признак — Ansible, создающий через API балансировщики: надёжно он этого не умеет, потому что не хранит состояние.

## Типичные ошибки

1. **State в git.** Секреты попадают в историю навсегда, а параллельные `apply` затирают друг друга. Причина — простота первого запуска: локальный файл появился сам и был закоммичен «на всякий случай».
2. **`apply` без просмотра плана.** Одна строка `- aws_db_instance.main will be destroyed` в плане означает потерю базы. Причина — привычка запускать `apply -auto-approve` в цикле отладки.
3. **Два инженера с локальным state.** Terraform у одного не видит ресурсы, созданные другим, и создаёт дубликаты с другими именами; счёт за месяц удваивается. Лечится remote backend с блокировкой.
4. **`count` вместо `for_each`.** При удалении второго элемента из списка `count = 3` Terraform пересоздаёт все последующие, потому что адреса `[0]`, `[1]`, `[2]` сдвигаются. `for_each` привязывает ресурс к ключу, и удаление одного не трогает остальные.
5. **`shell`/`command` вместо модулей в Ansible.** Задача всегда `changed`, идемпотентности нет, повторный прогон делает то же самое ещё раз. Причина — модуль для задачи не найден или лень читать документацию.
6. **`ignore_errors: true` и `failed_when: false`.** Ошибка маскируется, playbook зелёный, а сервис не настроен. Через месяц выясняется, что половина хостов конфигурировалась не так.
7. **Ручные правки после применения.** Изменение в консоли облака или на сервере создаёт дрейф ({{L|g32|drift}}): следующий `plan` покажет расхождение, а `apply` его затрёт. Причина — отсутствие запрета на ручные изменения и доступа к консоли без аудита.

## Чек-лист

- [ ] State в remote backend с шифрованием и блокировкой, в git только конфигурация.
- [ ] Версии Terraform и провайдеров зафиксированы диапазоном в `required_providers`.
- [ ] `plan` выполняется в CI на каждый pull request, `apply` — только из CI по сохранённому плану.
- [ ] У всех ресурсов есть теги проекта и окружения (через `default_tags` или `locals`).
- [ ] Модули используются там, где есть повторение, и версионируются.
- [ ] Playbook проходит повторный прогон с `changed=0` на неизменённой конфигурации.
- [ ] Секреты в Ansible зашифрованы vault, ключ не в git; задачи с секретами помечены `no_log`.
- [ ] Есть проверка конфигов перед применением: `terraform validate`, `ansible-playbook --check --diff`.

## Упражнения

1. Опишите в Terraform бакет объектного хранилища с версионированием, запретом публичного доступа и тегами. Добейтесь, чтобы повторный `plan` показывал `No changes`.
2. Перенесите state из локального файла в S3 с блокировкой. Убедитесь, что второй параллельный `apply` завершается ошибкой блокировки, а не повреждает state.
3. Напишите playbook, который ставит nginx, раскладывает конфиг из шаблона и перезапускает сервис только при изменении. Проверьте идемпотентность повторным прогоном.
4. Добавьте в playbook секрет из vault и убедитесь, что при `-vvv` значение не попадает в вывод.

*Ответы и разбор к этим упражнениям — в приложении D, часть 4.*
