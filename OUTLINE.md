# DevOps: от бита до кластера

## Структура книги (44 главы + приложения)

### Часть I. Основы Computer Science (гл. 1–8)
1. Что такое вычисление: автоматы, машина Тьюринга, вычислимость — `ch01_computation.md`
1a. Алгоритмика: как оценивать алгоритмы и не изобретать велосипед — `ch01a_algorithms.md`
2. Биты, числа и кодировки: от двоичного кода до UTF-8 — `ch02_bits_encoding.md`
3. Процессор и память: как код превращается в такты — `ch03_cpu_memory.md`
4. Операционная система: процессы, потоки, планировщик — `ch04_os_processes.md`
5. Виртуальная память и файловые системы — `ch05_vm_fs.md`
5a. Linux: пользователи, права, sudo — `ch05a_linux_permissions.md`
5b. Linux: пакеты, systemd, журналы — `ch05b_linux_systemd.md`
5c. Linux: namespaces, cgroups, диагностика — `ch05c_linux_namespaces.md`
5d. eBPF: наблюдение за ядром без пересборки — `ch05d_ebpf.md`
5e. SSH: ключи, конфиг, туннели — `ch05e_ssh.md`
6. Сети: от кабеля до IP-пакета — `ch06_networks_ip.md`
7. TCP и UDP: надёжность, порты, сокеты — `ch07_tcp_udp.md`
8. DNS: как имя становится адресом — `ch08_dns.md`

### Часть II. HTTP и интернет (гл. 9–15)
9. HTTP/1.1: запросы, ответы, заголовки — `ch09_http11.md`
10. HTTP/2 и HTTP/3: мультиплексирование и QUIC — `ch10_http23.md`
11. Куки, сессии, кэширование, CDN — `ch11_cookies_cache.md`
12. TLS и сертификаты — `ch12_tls.md`
12a. API: что это такое и как им пользоваться — `ch12a_api_intro.md`
13. REST и проектирование API — `ch13_rest_api.md`
14. Прокси, балансировщики, reverse proxy — `ch14_proxy_lb.md`
15. nginx и event loop: почему один процесс держит 10k соединений — `ch15_nginx_eventloop.md`

### Часть III. Python (гл. 16–24)
16. Окружение: интерпретатор, venv, пакеты, структура проекта — `ch16_python_env.md`
17. Синтаксис и типы: коллекции, срезы, comprehension — `ch17_python_types.md`
18. Функции, замыкания, декораторы, аргументы — `ch18_python_functions.md`
19. ООП, dataclasses, протоколы, MRO — `ch19_python_oop.md`
20. Асинхронность: asyncio, event loop, GIL — `ch20_python_async.md`
21. Сеть и API: httpx, таймауты, ретраи — `ch21_python_http.md`
22. Файлы, конфиги, логирование — `ch22_python_io.md`
23. Тесты: pytest, фикстуры, моки, coverage — `ch23_python_tests.md`
24. CLI и упаковка: typer, entry points, публикация — `ch24_python_cli.md`
24a. Makefile: контракт репозитория — `ch24a_make.md`

### Часть IV. Bash (гл. 25–29)
25. Шелл: переменные, кавычки, подстановки — `ch25_bash_basics.md`
26. Управляющие конструкции и коды возврата — `ch26_bash_control.md`
27. Текст: grep, sed, awk, jq, xargs, find — `ch27_bash_text.md`
28. Процессы, сигналы, перенаправления, job control — `ch28_bash_processes.md`
29. Практика: скрипты бэкапа, healthcheck, деплоя, systemd timers — `ch29_bash_practice.md`

### Часть V. Go (гл. 30–36)
30. Начало: модули, структура, go tool — `ch30_go_start.md`
31. Синтаксис: срезы, мапы, указатели, интерфейсы, ошибки — `ch31_go_syntax.md`
32. Конкурентность: горутины, каналы, context — `ch32_go_concurrency.md`
33. HTTP-сервер и клиент, middleware, graceful shutdown — `ch33_go_http.md`
34. Базы данных, пул соединений, миграции — `ch34_go_db.md`
34a. Очереди и асинхронная обработка — `ch34a_queues.md`
34b. SQL: индексы, планы, блокировки — `ch34b_sql.md`
35. Тесты, бенчмарки, pprof, race detector — `ch35_go_tests.md`
36. Сборка и поставка: статический бинарник, cross-compile, Docker — `ch36_go_build.md`

### Часть VI. DevOps-практика (гл. 37–44)
37. Git: модель данных, ветки, rebase, хуки — `ch37_git.md`
38. Docker: слои, Dockerfile, compose — `ch38_docker.md`
39. CI/CD: пайплайны, кэш, артефакты — `ch39_cicd.md`
39a. Бэкапы и восстановление — `ch39a_backups.md`
40. IaC: Terraform и Ansible — `ch40_iac.md`
41. Kubernetes: поды, деплойменты, сервисы, probes — `ch41_kubernetes.md`
41a. Helm и GitOps — `ch41a_helm_gitops.md`
42. Наблюдаемость: метрики, логи, трейсы, SLO — `ch42_observability.md`
42a. Нагрузочное тестирование — `ch42a_loadtesting.md`
43. Безопасность и supply chain — `ch43_security.md`
43a. Секреты: Vault, SOPS, age — `ch43a_secrets.md`
44. Инциденты, postmortem, on-call — `ch44_incidents.md`

### Приложения
- A. Чек-лист продакшн-сервиса — `app_a_checklist.md`
- B. Шпаргалки (bash, git, docker, kubectl, systemd) — `app_b_cheatsheets.md`
- C. Глоссарий — `app_c_glossary.md`
- D. Ответы и решения к упражнениям (5 частей) — `app_d1_answers.md` … `app_d5_answers.md`

## Linux, Docker и Kubernetes — где именно
- **Linux**: главы 4 (процессы), 5 (память и ФС), **5a (права и sudo)**, **5b (пакеты, systemd, journald)**,
  **5c (namespaces, cgroups, диагностика)**, 28 (сигналы), 29 (systemd-таймеры).
- **Docker**: глава 38 — устройство контейнера (namespaces + cgroups из 5c), слои, Dockerfile, compose.
- **Kubernetes**: глава 41 — поды, деплойменты, сервисы, probes, ресурсы; опирается на 38 и 5c.
- Связка намеренная: сначала «как Linux изолирует процесс» (5c), потом «как из этого делают контейнер»
  (38), потом «как оркестрируют контейнеры» (41).

## Принцип нарастания
Часть I — «как работает железо и ОС». Часть II — «как работает сеть и веб». Часть III — Python как
основной язык автоматизации. Часть IV — bash как клей. Часть V — Go как язык сервисов.
Часть VI — практика эксплуатации. Каждая глава ссылается на предыдущие, но читается отдельно.
