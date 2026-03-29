# Payment Processing Service

Асинхронный микросервис обработки платежей на FastAPI + RabbitMQ + PostgreSQL.



## Быстрый старт

### Предварительные требования

- Docker 24+
- Docker Compose v2

### Запуск

```bash
# Клонировать репозиторий
git clone https://github.com/say1ts/PaymentProcessingService
cd PaymentProcessingService

# Запустить все сервисы (postgres, rabbitmq, migrate, api, consumer)
docker compose up --build
```

Сервисы стартуют в правильном порядке:
1. `postgres` и `rabbitmq` — ждут healthcheck
2. `migrate` — применяет миграции Alembic и завершается
3. `api` и `consumer` — стартуют после успешной миграции

**API доступно:** `http://localhost:8000`  
**Swagger UI:** `http://localhost:8000/docs`  
**RabbitMQ Management:** `http://localhost:15672` (логин: `payments` / `payments_secret`)

### Остановка

```bash
docker compose down          # остановить контейнеры
docker compose down -v       # + удалить volumes (БД и очереди)
```

---



## Тесты

Для тестов нужен запущенный PostgreSQL (RabbitMQ не требуется — брокер не используется в тестах).

```bash
# Поднять только БД
docker compose up postgres -d

# Запустить тесты
pytest tests/ -v
```

```
tests/test_payments.py::TestPaymentsAPI::test_create_payment_success        PASSED
tests/test_payments.py::TestPaymentsAPI::test_create_payment_idempotency    PASSED
tests/test_payments.py::TestPaymentsAPI::test_get_payment_details           PASSED
tests/test_payments.py::TestPaymentsAPI::test_create_payment_validation_error PASSED
tests/test_payments.py::TestPaymentsAPI::test_unauthorized_access           PASSED
tests/test_payments.py::TestPaymentsAPI::test_get_non_existent_payment      PASSED
```

---

## Архитектура

```
┌─────────────┐    POST /payments     ┌─────────────────┐
│   Client    │──────────────────────▶│   FastAPI API   │
└─────────────┘                       └────────┬────────┘
                                               │ 1. Сохранить Payment (pending)
                                               │ 2. Сохранить OutboxEvent
                                               │    (одна транзакция)
                                               ▼
                                       ┌──────────────┐
                                       │  PostgreSQL  │
                                       └──────┬───────┘
                                              │
                                    ┌─────────▼─────────┐
                                    │  Outbox Poller    │
                                    │  (раз в 1 сек)    │
                                    └─────────┬─────────┘
                                              │ publish event
                                              ▼
                                    ┌──────────────────┐
                                    │    RabbitMQ      │
                                    │  payments.new    │──── (nack x3) ──▶ payments.dead
                                    └────────┬─────────┘                    (DLQ)
                                             │
                                    ┌────────▼─────────┐
                                    │    Consumer      │
                                    │  1. Gateway эмул │
                                    │  2. UPDATE status│
                                    │  3. Webhook POST │
                                    └──────────────────┘
```

**Гарантии доставки:**
- **Outbox pattern** — событие и платёж сохраняются атомарно в одной транзакции. Даже при падении сервиса до публикации в брокер, поллер подберёт необработанные события.
- **Idempotency key** — повторный запрос с тем же ключом возвращает тот же платёж без дублирования.
- **Retry с экспоненциальной задержкой** — 3 попытки: 1s → 2s → 4s. Счётчик хранится в БД, переживает перезапуск consumer-а.
- **DLQ** — после 3 неудачных попыток сообщение уходит в `payments.dead` через `x-dead-letter-exchange`.

---

## Стек

| Компонент | Технология |
|---|---|
| API | FastAPI 0.115 + Pydantic v2 |
| ORM | SQLAlchemy 2.0 (async) |
| БД | PostgreSQL 16 |
| Брокер | RabbitMQ 3.13 (FastStream + aio-pika) |
| Миграции | Alembic |
| Логирование | structlog (JSON в prod, цветной вывод в dev) |
| Контейнеризация | Docker + docker-compose |

---

## Локальная разработка

### Требования

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (или pip)
- PostgreSQL и RabbitMQ (можно поднять только инфраструктуру через Docker)

### Установка зависимостей

```bash
uv sync --dev
```

### Поднять только инфраструктуру

```bash
docker compose up postgres rabbitmq -d
```

### Переменные окружения

Создайте файл `.env` в корне проекта:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=payments
POSTGRES_PASSWORD=payments_secret
POSTGRES_DB=payments

RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=payments
RABBITMQ_PASSWORD=payments_secret
RABBITMQ_VHOST=/

API_KEY=dev_secret_key_change_in_production
LOG_LEVEL=INFO
ENVIRONMENT=development
```

### Применить миграции

```bash
alembic upgrade head
```

### Запустить API

```bash
uvicorn app.api.main:app --reload --port 8000
```

### Запустить Consumer

```bash
python -m consumer.main
```

---

## API

Все эндпоинты требуют заголовок `X-API-Key`.

### Создать платёж

```
POST /api/v1/payments
X-API-Key: <key>
Idempotency-Key: <uuid>
Content-Type: application/json
```

**Тело запроса:**

```json
{
  "amount": 1500.00,
  "currency": "RUB",
  "description": "Оплата заказа #42",
  "webhook_url": "https://your-service.example.com/webhook",
  "metadata": {
    "order_id": "42",
    "user_id": "123"
  }
}
```

**Ответ `202 Accepted`:**

```json
{
  "payment_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "pending",
  "created_at": "2024-01-15T12:00:00.000000Z"
}
```

**Возможные ошибки:**

| Код | Причина |
|-----|---------|
| `401` | Отсутствует или неверный `X-API-Key` |
| `422` | Ошибка валидации (отрицательная сумма, неверная валюта и т.д.) |

---

### Получить платёж

```
GET /api/v1/payments/{payment_id}
X-API-Key: <key>
```

**Ответ `200 OK`:**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "amount": "1500.00",
  "currency": "RUB",
  "description": "Оплата заказа #42",
  "metadata": { "order_id": "42" },
  "status": "succeeded",
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
  "webhook_url": "https://your-service.example.com/webhook",
  "failure_reason": null,
  "created_at": "2024-01-15T12:00:00.000000Z",
  "processed_at": "2024-01-15T12:00:04.123456Z"
}
```

**Возможные статусы:** `pending` → `succeeded` | `failed`

**Возможные ошибки:**

| Код | Причина |
|-----|---------|
| `401` | Отсутствует или неверный `X-API-Key` |
| `404` | Платёж не найден |

---

### Healthcheck

```
GET /health
```

```json
{ "status": "ok" }
```

---

## Webhook-уведомления

После обработки платежа consumer отправляет `POST`-запрос на `webhook_url`.

**Успешный платёж:**

```json
{
  "event": "payment.succeeded",
  "payment_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "transaction_id": "tx_a1b2c3d4e5f67890",
  "timestamp": "2024-01-15T12:00:04.123456+00:00"
}
```

**Неудачный платёж:**

```json
{
  "event": "payment.failed",
  "payment_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "failure_reason": "Insufficient funds",
  "timestamp": "2024-01-15T12:00:07.654321+00:00"
}
```

Webhook отправляется с retry: 3 попытки с экспоненциальной задержкой (1s, 2s, 4s). Локальные и приватные IP-адреса блокируются (SSRF-защита).

---

## Структура проекта

```
payments-service/
├── app/
│   ├── api/
│   │   ├── main.py              # FastAPI приложение, lifespan
│   │   ├── deps.py              # Зависимости: API-ключ, сессия БД
│   │   └── v1/
│   │       ├── payments.py      # Эндпоинты
│   │       └── schemas.py       # Pydantic-схемы запроса/ответа
│   ├── core/
│   │   ├── config.py            # Настройки через pydantic-settings
│   │   └── logging.py           # structlog (JSON / dev-консоль)
│   ├── domain/
│   │   ├── events.py            # Доменные события (PaymentCreated и др.)
│   │   ├── result.py            # Result type: Ok[T] | Err
│   │   └── value_objects.py     # Money, Currency
│   ├── infra/
│   │   ├── broker/
│   │   │   ├── publisher.py     # RabbitMQ publisher (aio-pika)
│   │   │   └── topology.py      # FastStream объекты для subscriber
│   │   ├── db/
│   │   │   ├── models.py        # SQLAlchemy ORM-модели
│   │   │   ├── repositories.py  # Функции доступа к данным
│   │   │   └── session.py       # Engine и session factory
│   │   ├── gateway/
│   │   │   └── emulator.py      # Эмуляция платёжного шлюза (2-5s, 90%/10%)
│   │   ├── outbox/
│   │   │   └── poller.py        # Outbox poller (SELECT FOR UPDATE SKIP LOCKED)
│   │   └── webhook/
│   │       └── sender.py        # HTTP-отправка с retry и SSRF-защитой
│   └── services/
│       └── payments.py          # Бизнес-логика: create_payment, get_payment
├── consumer/
│   ├── main.py                  # FastStream app, объявление топологии RabbitMQ
│   └── handler.py               # Обработчик сообщения: gateway → DB → webhook
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 0001_initial.py      # Таблицы payments и outbox_events
│       └── 0002_consumer_attempts.py  # Счётчик попыток consumer-а
├── tests/
│   ├── conftest.py              # Фикстуры: тестовая БД, HTTP-клиент
│   └── test_payments.py         # Интеграционные тесты API
├── Dockerfile.api
├── Dockerfile.consumer
├── docker-compose.yml
├── pyproject.toml
└── .env                         # (не коммитить)
```

---

## Конфигурация

Все параметры задаются через переменные окружения или файл `.env`.

| Переменная | По умолчанию | Описание |
|---|---|---|
| `API_KEY` | — | **Обязательно.** Статический API-ключ |
| `POSTGRES_HOST` | `localhost` | Хост PostgreSQL |
| `POSTGRES_PORT` | `5432` | Порт PostgreSQL |
| `POSTGRES_USER` | `postgres` | Пользователь БД |
| `POSTGRES_PASSWORD` | `postgres` | Пароль БД |
| `POSTGRES_DB` | `payments` | Имя базы данных |
| `RABBITMQ_HOST` | `localhost` | Хост RabbitMQ |
| `RABBITMQ_PORT` | `5672` | Порт AMQP |
| `RABBITMQ_USER` | `guest` | Пользователь RabbitMQ |
| `RABBITMQ_PASSWORD` | `guest` | Пароль RabbitMQ |
| `RABBITMQ_VHOST` | `/` | Virtual host |
| `ENVIRONMENT` | `development` | `development` или `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `OUTBOX_POLL_INTERVAL` | `1.0` | Интервал поллера в секундах |
| `GATEWAY_SUCCESS_RATE` | `0.9` | Вероятность успеха шлюза (0.0–1.0) |
| `GATEWAY_MIN_DELAY` | `2.0` | Минимальная задержка шлюза (сек) |
| `GATEWAY_MAX_DELAY` | `5.0` | Максимальная задержка шлюза (сек) |
| `WEBHOOK_RETRY_ATTEMPTS` | `3` | Попыток отправки webhook |
| `WEBHOOK_RETRY_BACKOFF` | `2.0` | База для экспоненциального backoff webhook |
| `CONSUMER_RETRY_ATTEMPTS` | `3` | Попыток обработки сообщения consumer-ом |
| `CONSUMER_RETRY_BACKOFF` | `2.0` | База для экспоненциального backoff consumer-а |
