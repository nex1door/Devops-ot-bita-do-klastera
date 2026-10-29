# Глава 41a. Helm и GitOps

В главе 41 манифесты применялись руками через `kubectl apply`. На одном сервисе это работает, на десяти сервисах в трёх окружениях — нет: одинаковые YAML расходятся по копиям, правки в кластере теряются, откатить «весь релиз» нечем. Дальше два инструмента и один принцип: Helm упаковывает манифесты в параметризованный чарт, Kustomize решает ту же задачу патчами, а {{L|g142|GitOps}} делает git единственным источником правды. Примеры — полный чарт сервиса и Application для Argo CD.

## Проблема сырых манифестов

Первый рефакторинг обычно выглядит так: `manifests/dev/api.yaml`, `staging/api.yaml`, `prod/api.yaml`. Файлы совпадают на 90%, различаются репликами, тегом образа и хостом в {{L|g54|Ingress}}. Дальше кто-то правит лимиты в проде и забывает про staging, кто-то во время инцидента делает `kubectl edit` и не переносит изменение в git.

Три поломки. Копипаста: изменение в общей части нужно внести трижды, и одна из копий всегда отстаёт. Дрейф ({{L|g32|drift}}): живое состояние расходится с git, потому что `kubectl edit`, `scale` и правки руками никем не отслеживаются. Нет единицы отката: `kubectl rollout undo` возвращает только {{L|g27|Deployment}}, а релиз — это ещё {{L|g104|Service}}, Ingress, ConfigMap и миграция.

Helm и Kustomize решают первую и третью проблемы, GitOps — вторую.

## Helm: chart, шаблоны, values

Чарт (chart) — каталог с шаблонами и значениями (Helm 3, актуальная ветка на момент написания):

```
charts/shop-api/
├── Chart.yaml          # метаданные: имя, версия чарта, версия приложения
├── values.yaml         # значения по умолчанию
├── values-prod.yaml    # переопределения для прода
└── templates/
    ├── _helpers.tpl    # именованные шаблоны, не рендерятся сами
    └── app.yaml        # Deployment + Service + Ingress
```

`helm template` рендерит шаблоны локально и печатает YAML, ничего не отправляя в кластер, — это главный инструмент отладки. `helm upgrade --install` отправляет результат в API-сервер и записывает релиз (release) в Secret внутри namespace: имя, ревизию, отрендеренный манифест. Из этих записей работают `helm history` и `helm rollback`.


## Чарт целиком: три файла

`Chart.yaml`:

```yaml
apiVersion: v2
name: shop-api
description: HTTP API магазина
type: application
version: 1.8.0
appVersion: "2.14.3"
kubeVersion: ">=1.35.0-0"
```

`values.yaml` — все ручки с осмысленными значениями по умолчанию:

```yaml
replicaCount: 3
image:
  repository: ghcr.io/example/shop-api
  tag: ""          # пусто → тег берётся из appVersion
service:
  port: 80
ingress:
  enabled: true
  className: nginx
  host: shop.example.com
  tlsSecret: shop-tls
resources:
  requests: {cpu: 100m, memory: 192Mi}
  limits: {memory: 256Mi}
extraEnv: []
```

`templates/app.yaml` — три объекта в одном файле, разделённые `---`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-api
  labels:
    app.kubernetes.io/name: shop-api
    app.kubernetes.io/instance: {{ .Release.Name }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app.kubernetes.io/name: shop-api
      app.kubernetes.io/instance: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: shop-api
        app.kubernetes.io/instance: {{ .Release.Name }}
    spec:
      containers:
        - name: api
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          ports:
            - name: http
              containerPort: 8000
          {{- with .Values.extraEnv }}
          env:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}-api
spec:
  selector:
    app.kubernetes.io/name: shop-api
    app.kubernetes.io/instance: {{ .Release.Name }}
  ports:
    - name: http
      port: {{ .Values.service.port }}
      targetPort: http
---
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Release.Name }}-api
spec:
  ingressClassName: {{ .Values.ingress.className }}
  tls:
    - hosts: [{{ .Values.ingress.host | quote }}]
      secretName: {{ .Values.ingress.tlsSecret }}
  rules:
    - host: {{ .Values.ingress.host | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ .Release.Name }}-api
                port:
                  name: http
{{- end }}
```

Разбор. `.Release.Name` — имя релиза из `helm upgrade`, а не из чарта: один чарт можно поставить дважды в разные namespace без конфликта имён. `image.tag | default .Chart.AppVersion` делает appVersion значением по умолчанию для тега, но в проде тег задаётся явно. `{{- with }}` пропускает блок, если список пуст, а минус в `{{-` съедает перевод строки слева, иначе в YAML остаётся пустая строка. `toYaml | nindent 12` вставляет структуру с отступом 12 пробелов — самый частый источник ошибок «неверный отступ в отрендеренном манифесте».

## Окружения: values-prod.yaml

`values-prod.yaml` содержит только отличия:

```yaml
replicaCount: 6
image:
  tag: "2.14.3"
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    memory: 1Gi
ingress:
  host: shop.example.com
```

Файлы применяются по порядку, побеждает последний: `-f values.yaml -f values-prod.yaml`. Вложенные словари сливаются по ключам, а списки заменяются целиком — это ломает `extraEnv`, добавленный в prod-файле: он не дополняет, а вытесняет базовый список.

Правило, которое экономит инциденты: **в values.yaml есть все ключи с рабочими значениями по умолчанию, env-файлы только переопределяют**. Тогда `helm template` без `-f` даёт валидный манифест, а не пустые поля.

## helpers, условия, range

Повторяющиеся метки выносят в `templates/_helpers.tpl`. Файлы с подчёркиванием не рендерятся в манифесты, из них только берут `include`:

```
{{- define "shop-api.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
```

Использование в шаблоне:

```yaml
metadata:
  name: {{ include "shop-api.fullname" . }}
  labels:
    {{- include "shop-api.labels" . | nindent 4 }}
```

`include` возвращает строку, `template` печатает её на месте — поэтому в пайплайнах с `nindent` используется только `include`. Точка в конце (`include ... .`) передаёт текущий контекст, без неё внутри хелпера не будет `.Chart` и `.Values`.

Условия и циклы закрывают вариативность без копирования файлов: `{{- if .Values.ingress.enabled }}` убирает Ingress целиком, `{{- range .Values.extraEnv }}` разворачивает список, `required` валит рендер с понятным сообщением вместо пустого хоста.

## Команды: template, diff, upgrade, rollback

```bash
helm lint ./charts/shop-api
helm template shop ./charts/shop-api -f values-prod.yaml | head -40
helm diff upgrade shop ./charts/shop-api -n shop -f values-prod.yaml
helm upgrade --install shop ./charts/shop-api -n shop --create-namespace \
  -f values-prod.yaml --atomic --wait --timeout 5m
helm history shop -n shop
helm rollback shop 4 -n shop --wait
```

`helm diff` — плагин, не часть Helm, но без него `upgrade` превращается в лотерею: он показывает, какие поля изменятся до применения. `--atomic` включает `--wait` и откатывает релиз, если поды не стали Ready за `--timeout`; без него неудачный выкат остаётся `deployed`, а половина объектов — в новой версии. `--wait` ждёт готовности Deployment и Job, но не проверяет, что приложение отвечает правильно: за это отвечает smoke-тест.

`helm rollback` возвращает манифест предыдущей ревизии. Важная деталь: он не пересобирает образ и не откатывает миграции БД. Если тег образа в values не менялся, откат вернёт тот же самый тег и ничего не изменит.

## Версии: chart version и appVersion

Два разных поля, которые постоянно путают. `version` — версия чарта по semver, обязательна, увеличивается при любом изменении шаблонов или values. `appVersion` — версия приложения, строка в кавычках; Helm её нигде не использует, кроме `.Chart.AppVersion`, которую вы сами подставляете в тег.

Отсюда правило релиза: тег образа — неизменяемый (хэш коммита или semver), `version` чарта инкрементируется в том же коммите, `appVersion` совпадает с тегом. Публикация в OCI-реестр — `helm package` и `helm push shop-api-1.8.0.tgz oci://ghcr.io/example/charts`.

## Почему Helm не любят и Kustomize

Претензия к Helm честная: шаблоны — это язык программирования на YAML, с циклами, условиями и ошибками, которые вылезают только при рендере. Отладка идёт через `--debug`, типов нет, `values.schema.json` пишут редко. Второе: чарт — ещё один артефакт, который надо версионировать и публиковать.

Kustomize идёт другим путём: базовые манифесты остаются обычным Kubernetes YAML в `base/`, а окружения — каталоги `overlays/prod/` с патчами (`patches`) и подменой тега (`images`). Шаблонов нет, есть наложение изменений на структуру.

| Критерий | Helm | Kustomize |
|---|---|---|
| Изменения | шаблоны и values | патчи поверх base |
| Сложная логика | условия, range, хелперы | нет, только структура |
| Версионирование | `version` чарта, реестр | версия = коммит git |
| Отладка | `helm template --debug` | `kustomize build` |
| Когда выбирать | много похожих сервисов, публикация | несколько окружений одного сервиса |

Они не конкуренты: Kustomize умеет подключать чарты (`helmCharts`), Argo CD поддерживает оба рендерера.

## GitOps: git как источник правды

GitOps — это не инструмент, а правило: желаемое состояние кластера описано в git, и только там. Изменение в кластере делается коммитом, а не `kubectl`. Из правила следуют три свойства.

История: `git log` по каталогу приложения — история деплоев, с автором и причиной. Откат: `git revert` возвращает и манифесты, и образ, и конфигурацию. Безопасность: кластер сам тянет изменения из git, поэтому CI не хранит kubeconfig и не имеет прав в продакшене — самая частая дыра в схеме «CI делает `kubectl apply`».

Механика — цикл сверки (reconcile loop): контроллер раз в несколько минут или по вебхуку из git сравнивает желаемое состояние с живым и применяет расхождения. Это и есть drift detection — отличие не «замечается» отдельным скриптом, а исчезает при сверке.

## Argo CD: Application и ApplicationSet

Application — объект, который связывает каталог в git с namespace в кластере (Argo CD 2.x на момент написания):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: shop-api
  namespace: argocd
spec:
  project: shop
  source:
    repoURL: https://github.com/example/shop-deploy.git
    targetRevision: main
    path: charts/shop-api
    helm:
      valueFiles: [values-prod.yaml]
  destination:
    server: https://kubernetes.default.svc
    namespace: shop
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
```

`automated` включает автоприменение при расхождении. `selfHeal` возвращает украденные ресурсы к состоянию git — он и делает `kubectl edit` бессмысленным. `prune` удаляет объекты, исчезнувшие из git: без него удалённый Deployment остаётся в кластере навсегда, а с ним есть риск снести лишнее.

Когда приложений десятки, их не пишут руками — их генерирует ApplicationSet:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: shop-api-envs
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - list:
        elements:
          - {env: staging, namespace: shop-staging}
          - {env: production, namespace: shop}
  template:
    metadata:
      name: 'shop-api-{{ .env }}'
    spec:
      project: shop
      source:
        repoURL: https://github.com/example/shop-deploy.git
        targetRevision: main
        path: charts/shop-api
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{ .namespace }}'
```

Генератор `list` — простейший; `git` создаёт Application на каждый каталог в репозитории, и добавление окружения сводится к созданию каталога.

## Дрейф и откат через git revert

`argocd app diff shop-api` показывает расхождение между живым состоянием и тем, что рендерится из git: какие поля изменены, какие объекты лишние, каких не хватает. Пустой вывод — единственный надёжный признак, что кластер соответствует репозиторию.

Откат делается `git revert`, а не кнопкой в UI: `selfHeal` вернёт состояние git через минуты, поэтому «откат в Argo» живёт до следующей сверки. Последовательность: revert коммита, `Synced`, `argocd app diff`, smoke-тест.

## Секреты в GitOps

Правило «всё в git» упирается в секреты: пароль в открытом виде — утечка, а без него чарт не рендерится. Решения: SOPS с age или KMS (шифрованный файл в git, расшифровка на стороне контроллера), Sealed Secrets (можно коммитить, расшифрует только контроллер), External Secrets Operator (в git ссылка на запись {{L|g152|Vault}}). Подробно — в главе 43a.

## Порядок выката: sync waves и hooks

Обычно Argo применяет объекты параллельно, и это ломает сценарии, где миграция должна пройти до нового пода. Порядок задаёт аннотация `argocd.argoproj.io/sync-wave`: объекты с меньшим номером применяются раньше, с одинаковым — параллельно.

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
```

Для разовых действий (миграция схемы, прогрев кэша) есть хуки: Job с `argocd.argoproj.io/hook: PreSync` выполняется до применения манифестов, `PostSync` — после, `hook-delete-policy` убирает его за собой. Практика: миграция отдельным PreSync Job, Deployment в волне 0, Ingress — в волне 1.

## Типичные ошибки

1. **`latest` или `appVersion` вместо тега.** Механизм: удобно не менять values, но `helm rollback` вернёт манифест с тем же тегом, и откат ничего не откатит.
2. **`helm upgrade` без `--atomic`.** Механизм: релиз помечается `deployed`, даже если поды не поднялись; часть объектов остаётся в новой версии, часть — в старой.
3. **Секреты в values.yaml.** Механизм: «потом зашифруем», а репозиторий уже склонирован, и история git хранит значение навсегда.
4. **`kubectl edit` при включённом `selfHeal`.** Механизм: правка живёт до следующей сверки, потом молча исчезает — это выглядит как «изменения не применяются».
5. **`prune` без разбора.** Механизм: удалили каталог из git или переименовали объект — Argo удалил ресурс, включая PVC с данными.
6. **Один Application на весь монорепозиторий.** Механизм: любой коммит перекатывает всё сразу, `sync waves` не помогают, откат одного сервиса тянет за собой остальные.

## Чек-лист

- [ ] `version` чарта увеличивается в том же коммите, что и изменение шаблонов; тег образа неизменяем.
- [ ] В values.yaml есть все ключи с рабочими значениями, env-файлы только переопределяют.
- [ ] `helm lint` и `helm template` прогоняются в CI, диф чарта показывается в PR.
- [ ] Выкат идёт с `--atomic --wait --timeout`, откат проверен хотя бы раз.
- [ ] Секретов в git нет: SOPS, Sealed Secrets или External Secrets.
- [ ] После синка `argocd app diff` пуст, `selfHeal` включён, `prune` осознан.
- [ ] Порядок выката задан sync waves, миграции — отдельным PreSync Job.
- [ ] Откат описан как `git revert`, а не как кнопка в UI.

## Упражнения

1. Соберите чарт из трёх файлов для своего сервиса, отрендерите `helm template` с разными values и сравните вывод: какие поля меняются, какие остаются.
2. Добавьте helpers для меток и `required` для хоста Ingress. Добейтесь, чтобы рендер без `ingress.host` падал с понятным сообщением.
3. Переведите те же манифесты на Kustomize (base + два overlay) и опишите, какие изменения дались проще, а какие — сложнее, чем в Helm.
4. Разверните Argo CD, заведите Application на свой репозиторий с `selfHeal: true`. Измените реплики через `kubectl scale` и объясните, что произошло.
5. Сделайте релиз из двух коммитов: в первом ошибка в образе, во втором исправление. Откатитесь через `git revert` и покажите в `argocd app history`, что состояние вернулось.

*Ответы и разбор к этим упражнениям — в приложении D, часть 5.*
