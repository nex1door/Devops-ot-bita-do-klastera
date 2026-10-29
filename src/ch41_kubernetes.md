# Глава 41. Kubernetes: поды, деплойменты, сервисы, probes

Kubernetes решает одну задачу: поддерживать заданное состояние набора контейнеров на наборе машин, даже когда машины падают. Всё остальное — сервисы, деплойменты, probes — следствия из этого принципа. В главе разбираются объекты, которых достаточно для 90% рабочих задач: под, {{L|g27|Deployment}}, Service, Ingress, ConfigMap, Secret, probes и requests/limits. Отдельно — диагностика через `kubectl` и четыре аварии: CrashLoopBackOff, ImagePullBackOff, {{L|g79|OOMKilled}} и Pending. Манифесты соответствуют API, актуальному для поддерживаемых версий 1.35–1.37.

## Зачем оркестратор

Один сервер с `docker compose` живёт, пока живы железо и Docker. Упал диск — сервис лежит, пока дежурный не поднимет. Нагрузка выросла вдвое — нужно вручную перенести контейнеры на вторую машину и проверить, что база видит новую реплику.

Оркестратор берёт на себя три вещи. Размещение: выбирает узел, где хватает CPU и памяти, с учётом меток, taint'ов и anti-affinity. Самовосстановление: перезапускает контейнеры, пересоздаёт поды на других узлах, если узел перестал отвечать. Декларативное управление: вы описываете желаемое состояние, контроллеры бесконечно приводят к нему текущее.

Цена — сложность: Kubernetes несёт собственный API, сетевую модель, планировщик и набор абстракций, которые надо понимать, чтобы не выстрелить в ногу. В проекте с одним сервисом он часто избыточен, в проекте с десятком сервисов — почти неизбежен.

## Под и контейнер

Под (Pod) — минимальная единица планирования: один или несколько контейнеров, которые делят сетевой namespace и тома. У пода один IP, контейнеры видят друг друга через `localhost`, запускаются на одном узле.

В продакшене поды не создают напрямую — ими управляет контроллер, иначе после падения узла никто не создаст замену. Для разовой отладки сети хватает `kubectl run debug --image=curlimages/curl:8.10.1 --restart=Never -- sleep infinity`.

Следствия из «один IP на под»: порты контейнеров внутри пода не могут конфликтовать, а sidecar обязан слушать другой порт; имя пода содержит случайный суффикс, поэтому обращаться к нему по имени нельзя.

## Deployment и ReplicaSet

Deployment описывает желаемое состояние приложения: образ, число реплик, стратегию обновления, шаблон пода. Он создаёт {{L|g96|ReplicaSet}}, а тот — поды. Новый шаблон даёт новый ReplicaSet, старый масштабируется вниз, а история ревизий остаётся — это и есть механизм отката.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: shop
  labels:
    app.kubernetes.io/name: api
spec:
  replicas: 3
  revisionHistoryLimit: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: api
  template:
    metadata:
      labels:
        app.kubernetes.io/name: api
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        fsGroup: 1001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: api
          image: ghcr.io/example/shop-api:a1b2c3d
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8000
          envFrom:
            - configMapRef:
                name: api-config
            - secretRef:
                name: api-secrets
          resources:
            requests:
              cpu: 100m
              memory: 192Mi
            limits:
              memory: 256Mi
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 3
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 2
          livenessProbe:
            httpGet:
              path: /livez
              port: http
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3
          startupProbe:
            httpGet:
              path: /healthz
              port: http
            periodSeconds: 2
            failureThreshold: 30
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
---
apiVersion: v1
kind: Service
metadata:
  name: api
  namespace: shop
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: api
  ports:
    - name: http
      port: 80
      targetPort: http
```

Разберём ключевые поля. `selector.matchLabels` и `template.metadata.labels` должны совпадать: иначе ReplicaSet не найдёт ни одного пода и будет плодить новые. `image` с хэшем коммита вместо `latest` обязателен: при `IfNotPresent` узел с закэшированным образом оставит старую версию. `runAsNonRoot` роняет под на старте, если образ пытается запуститься от root.

## Service: ClusterIP, NodePort, LoadBalancer

Service даёт стабильную точку входа поверх нестабильных подов: постоянное имя в DNS кластера, постоянный виртуальный IP и `Endpoints`, которые контроллер обновляет при каждом изменении набора подов.

| Тип | Доступность | Когда использовать |
|---|---|---|
| ClusterIP | только внутри кластера | общение сервисов, база |
| NodePort | порт на каждом узле | отладка, свой балансировщик |
| LoadBalancer | внешний LB провайдера | публикация наружу |
| ExternalName | CNAME на внешний DNS | сервис вне кластера |

`ClusterIP` — тип по умолчанию и правильный выбор для внутренних зависимостей: база не должна быть доступна через `NodePort`. `NodePort` открывает порт 30000–32767 на каждом узле. `LoadBalancer` создаёт облачный LB на каждый сервис — дорого, поэтому наружу публикуют один Ingress-контроллер.

Балансировка внутри Service не учитывает загрузку подов: {{L|g60|kube-proxy}} раскидывает соединения, sticky sessions требуют `sessionAffinity: ClientIP`. Учёт HTTP — задача ingress или mesh.

Service находит поды по меткам, поэтому `kubectl get endpoints api` — быстрая проверка селектора. Пустой список объясняет 503 от ingress без единой ошибки в логах.

## Ingress

Ingress — правила маршрутизации HTTP на уровне L7: хост, путь, TLS, сервис. Сам объект ничего не делает: нужен контроллер (ingress-nginx, Traefik), который читает объекты и настраивает прокси.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  namespace: shop
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - shop.example.com
      secretName: shop-tls
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: api
                port:
                  name: http
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  number: 80
```

`pathType: Prefix` совпадает по сегментам: `/api` поймает `/api/v1/orders`, но не `/apiv2`. `tls.secretName` ссылается на Secret с сертификатом, который создаёт cert-manager. Аннотации специфичны для контроллера: при переносе между nginx и Traefik их придётся переписать.

## ConfigMap и Secret

ConfigMap хранит конфигурацию, Secret — чувствительные значения. Технически Secret — тот же объект, но значения закодированы base64 и по умолчанию не шифруются: в etcd они лежат открыто, если не включено шифрование at-rest. Base64 — кодирование, а не защита.

```bash
kubectl -n shop create configmap api-config \
  --from-literal=APP_ENV=production \
  --from-literal=LOG_LEVEL=info

kubectl -n shop create secret generic api-secrets \
  --from-literal=DATABASE_URL="$DATABASE_URL"
```

Секреты из внешних хранилищ предпочтительнее: External Secrets Operator или Secrets Store CSI Driver создают Secret из значений Vault, так что в git не попадает ничего, а ротация делается в одном месте.

`envFrom` подставляет все ключи ConfigMap переменными окружения, но изменения не подхватываются без перезапуска подов. `volumeMount` обновляет файл в поде автоматически (с задержкой до минуты), однако приложение должно читать файл, а не окружение.

## requests, limits и QoS

`requests` — сколько ресурсов планировщик резервирует для пода. `limits` — потолок: превышение CPU-лимита ведёт к троттлингу, памяти — к OOMKilled.

Правило: **requests определяют размещение, limits определяют выживание**. Заниженные requests — планировщик напихает на узел больше подов, чем он тянет. Лимит памяти, равный request, не даст использовать всплеск, и под будет убит при пике.

Из соотношения requests и limits Kubernetes выводит класс QoS:

| Класс | Условие | Кого убивают первым |
|---|---|---|
| Guaranteed | requests = limits у всех контейнеров | последним |
| Burstable | requests < limits | по потреблению сверх requests |
| BestEffort | ничего не задано | первым |

Базе и критичным сервисам нужен Guaranteed: одинаковые requests и limits. Веб-приложениям разумно Burstable с memory limit в 2–3 раза выше request. BestEffort допустим только для отладки.

## Probes

Три проверки отвечают на три разных вопроса, и путать их — самая частая причина «странных» рестартов.

**livenessProbe** — «процесс жив?». Провал ведёт к перезапуску. Проверять надо сам факт ответа, а не доступность базы: иначе падение БД вызовет рестарт всех подов и полный отказ вместо деградации.

**readinessProbe** — «можно отправлять трафик?». Провал убирает под из Endpoints, но не перезапускает — это правильное место для проверки зависимостей: база недоступна, под не готов, трафик идёт на остальные.

**startupProbe** — «приложение уже загрузилось?». Пока она не прошла, остальные probes не выполняются. Нужна сервисам с долгим стартом: без неё liveness убьёт приложение на 30-й секунде инициализации, которая занимает минуту.

Бюджеты в манифесте выше: старт — до 60 секунд (30 попыток по 2), рестарт после 30 секунд провалов liveness, вывод из балансировки после двух провалов readiness с периодом 5 секунд.

Эндпоинты должны быть дешёвыми: проверка с тяжёлым запросом в базу каждые 5 секунд на 50 подах создаёт нагрузку больше, чем сам сервис.

## Rolling update: maxSurge и maxUnavailable

При обновлении Deployment создаёт новый ReplicaSet и переносит реплики: `maxSurge` — сколько подов можно создать сверх желаемого, `maxUnavailable` — сколько может быть недоступно.

По умолчанию 25% и 25%: для трёх реплик один под недоступен, один создаётся дополнительно. С `maxUnavailable: 0` и `maxSurge: 1` обновление идёт без потери ёмкости, но требует свободных ресурсов — иначе новые поды уйдут в Pending.

```bash
kubectl -n shop rollout status deployment/api --timeout=180s
kubectl -n shop rollout history deployment/api
kubectl -n shop rollout undo deployment/api --to-revision=3
```

Выкат «завис» почти всегда потому, что новый под не становится Ready: старые поды продолжают работать, и это правильно — плохая версия не должна вытеснить хорошую.

## HPA в двух словах

HorizontalPodAutoscaler меняет `replicas` по метрике. В `autoscaling/v2` это CPU, память или внешние метрики.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api
  namespace: shop
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 3
  maxReplicas: 12
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
```

HPA работает только при заданных `requests` по CPU: утилизация считается в процентах от request. `stabilizationWindowSeconds` не даёт масштабироваться вниз при коротком провале трафика.

## Диагностика через kubectl

Порядок действий почти всегда одинаков:

```bash
kubectl -n shop get pods -o wide
kubectl -n shop describe pod api-7d9f8c6b5-x2l4q
kubectl -n shop logs api-7d9f8c6b5-x2l4q --tail=100
kubectl -n shop logs api-7d9f8c6b5-x2l4q --previous
kubectl -n shop exec -it api-7d9f8c6b5-x2l4q -- sh
kubectl -n shop port-forward svc/api 8080:80
kubectl -n shop get events --sort-by=.lastTimestamp | tail -20
kubectl top pods -n shop
```

`get pods -o wide` показывает узел и IP. `describe` — главный инструмент: в конце есть `Events`, где видно, что решил планировщик и почему kubelet не смог запустить контейнер. `logs --previous` читает логи убитого контейнера — единственный способ увидеть причину падения.

## Четыре аварии

**CrashLoopBackOff.** Контейнер стартует, падает и перезапускается с растущей паузой (10с, 20с, 40с… до 5 минут). Причина в приложении или конфигурации: нет переменной, неверная строка подключения, падение на миграции. `describe` покажет `Exit Code: 1`, `logs --previous` — стектрейс. Увеличивать `initialDelaySeconds` бессмысленно: проблема не в скорости старта.

**ImagePullBackOff.** Kubelet не может скачать образ: неверный тег, приватный registry без `imagePullSecrets`, истёкший токен. `describe` покажет `unauthorized` или `manifest unknown`. Проверять надо доступ, а не кластер.

**OOMKilled.** Контейнер превысил memory limit, ядро убило процесс, {{L|g38|exit code}} 137. Причины: лимит меньше реального потребления, утечка, всплеск на большом запросе. Повышать лимит вслепую не стоит — смотрите `kubectl top pod` в динамике.

**Pending.** Под не размещён ни на одном узле: `Insufficient cpu`, `untolerated taint` или `didn't match node affinity`. Причины — нехватка ресурсов, метки, непривязанный PVC. Приложение не запускалось, искать ошибку в нём бессмысленно.

## Типичные ошибки

1. **`latest` в образе.** `imagePullPolicy: IfNotPresent` означает, что узел с закэшированным `latest` не обновится, а откат некуда делать. Причина — удобство ручных пушей; лечится хэшем коммита.
2. **liveness проверяет базу.** Падение базы вызывает каскадный рестарт всех подов и полный отказ. Причина — желание «проверить всё»; зависимости проверяет readiness.
3. **Нет requests.** Планировщик считает под нулевым по ресурсам, напихивает их на узел, и при первой нагрузке всё уходит в OOM и троттлинг. Причина — манифест «чтобы запустилось быстрее».
4. **limit = request для всех подряд.** Сервис не может использовать всплеск, а при малейшем превышении его убивают. Для stateless-сервисов разумнее Burstable.
5. **Секреты в ConfigMap.** Пароли в ConfigMap видны всем, у кого есть `get configmaps`, и попадают в `kubectl describe`. Причина — «Secret всё равно base64, какая разница».
6. **`kubectl edit` в проде.** Изменение живёт до следующего выката, потом исчезает; причина инцидента теряется. Всё идёт через git.

## Чек-лист

- [ ] Образ зафиксирован по хэшу коммита, `imagePullPolicy` осознан.
- [ ] У всех контейнеров заданы requests и limits; для критичных — Guaranteed.
- [ ] Readiness проверяет зависимости, liveness — только живость процесса.
- [ ] Для медленно стартующих сервисов есть startupProbe.
- [ ] `maxUnavailable` не равен 100%, выкат не роняет ёмкость до нуля.
- [ ] Секреты не в ConfigMap и не в git; доступ к ним ограничен RBAC.
- [ ] Есть `PodDisruptionBudget`, чтобы drain узла не убил все реплики сразу.
- [ ] Манифесты применяются из git, а не через `kubectl edit`/`apply` руками.

## Упражнения

1. Разверните Deployment с тремя репликами и Service типа ClusterIP. Убедитесь, что `kubectl get endpoints` содержит три адреса, затем сломайте селектор и объясните, что изменилось.
2. Настройте три probe для приложения, которое стартует 40 секунд. Добейтесь, чтобы без startupProbe поды рестартовали, а с ней — нет.
3. Задайте memory limit 64 МБ приложению, которое потребляет 100 МБ. Найдите в `describe` причину завершения и объясните разницу между exit code 137 и 1.
4. Сделайте {{L|g99|rolling update}} с `maxUnavailable: 0`, `maxSurge: 1` на кластере без свободных ресурсов. Разберитесь, почему поды ушли в Pending, и предложите два способа исправить.

*Ответы и разбор к этим упражнениям — в приложении D, часть 4.*
