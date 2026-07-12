# Operating Assumptions — Kettu Squeeze v0.1.x

Этот документ определяет, в каких условиях Kettu Squeeze спроектирован, протестирован и считается безопасным. Отклонение от supported deployment не является скрытым дефектом реализации — это нецелевой сценарий, требующий отдельного hardening.

## Supported Deployment

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| Процесс | Single-process MCP (stdio) | Нет тестов concurrent writes |
| Файловая система | Локальная | Content-addressed blob storage |
| Агент | Доверенный (Hermes, OpenClaw) | Команды формируются агентом, не пользователем |
| Транспорт | stdio (MCP) или localhost HTTP | Нет аутентификации, нет TLS |
| Аренда | Single tenant | Нет изоляции между пользователями |
| Артефакты | Локальный `~/.kettu-squeeze/` | Нет распределённого хранения |
| База данных | Локальный SQLite WAL | Нет network FS, нет shared DB |
| Сеть | Отсутствует (air-gap совместим) | Нет remote API, нет телеметрии |
| Масштабирование | Один агент, одна сессия | Нет горизонтального масштабирования |
| Модель | Любая (DeepSeek, GPT-OSS, локальная) | Не зависит от модели |

## Unsupported Deployment

Эти сценарии явно не поддерживаются в v0.1.x. Использование в них — на свой риск.

| Сценарий | Почему не поддерживается | Что нужно для поддержки |
|----------|--------------------------|------------------------|
| Multi-tenant SaaS | Нет аутентификации, нет изоляции артефактов | Auth, tenant isolation, quota |
| Internet-facing HTTP API | Нет аутентификации, нет rate limiting, нет TLS | FastAPI auth middleware, HTTPS |
| Shared SQLite over NFS | SQLite WAL не рассчитан на network FS | Переход на PostgreSQL/etcd |
| Untrusted shell input | `shell=True` без allowlist | `shell=False` + argv array + allowlist |
| Multiple concurrent writers | Не тестировалось | Connection pooling, WAL checkpoint tuning |
| Kubernetes horizontal scaling | Нет распределённого artifact store | Object storage (S3/MinIO) |
| Distributed artifact storage | Локальный content-addressed blob store | Распределённый CAS-слой |

## Explicitly Out of Scope

Следующее не является целью проекта и не планируется:

- Real-time compression streaming
- GPU-accelerated compression
- Network protocols (gRPC, WebSocket)
- Plugin system for custom compressors
- Cloud deployment templates
- Web UI / dashboard
- Multi-language SDK (только Python + MCP)

## Если вам нужно то, чего нет в Supported

1. Откройте issue с описанием сценария
2. Мы оценим, входит ли это в scope следующего minor-релиза
3. Не запускайте текущую версию в unsupported режиме без собственного hardening

## Стабильность ветки v0.1.x

- Новые функции: **заморожены**
- Bug fixes: принимаются
- Security fixes: принимаются немедленно
- Compatibility fixes: принимаются
- Изменение supported/unsupported списка: через документированное обсуждение
