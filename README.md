# Payment Processing Service

Асинхронный микросервис обработки платежей на FastAPI + RabbitMQ + PostgreSQL.

## Архитектура

```
POST /api/v1/payments
        │
        ▼
  [API] INSERT payments + outbox_events  ← одна транзакция
        │
        ▼
  [OutboxPoller] SELECT FOR UPDATE SKIP LOCKED
        │
        ▼
  [RabbitMQ] payments.exchange → payments.new
        │
        ▼
  [Consumer] GatewayEmulator (2-5s, 90% success)
        │
        ├─ Ok  → UPDATE status=succeeded → webhook
        └─ Err → UPDATE status=failed   → webhook
                              │
                         3 nack → DLX → payments.dead
```

## Запуск

```bash
# 1. Клонировать и перейти в директорию
cp .env.example .env

# 2. Поднять все сервисы
docker-compose up --build

# 3. Проверить что всё поднялось
curl http://localhost:8000/health
```

RabbitMQ Management UI: http://localhost:15672  
Логин: `payments` / `payments_secret`

## API

### Создать платёж

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev_secret_key_change_in_production" \
  -H "Idempotency-Key: unique-key-001" \
  -d '{
    "amount": "100.00",
    "currency": "RUB",
    "description": "Оплата заказа #42",
    "metadata": {"order_id": 42},
    "webhook_url": "https://webhook.site/your-unique-id"
  }'
```

**Ответ 202:**
```json
{
  "payment_id": "a1b2c3d4-...",
  "status": "pending",
  "created_at": "2024-01-01T12:00:00Z"
}
```

### Получить платёж

```bash
curl http://localhost:8000/api/v1/payments/a1b2c3d4-... \
  -H "X-API-Key: dev_secret_key_change_in_production"
```

**Ответ 200:**
```json
{
  "id": "a1b2c3d4-...",
  "amount": "100.00",
  "currency": "RUB",
  "description": "Оплата заказа #42",
  "metadata": {"order_id": 42},
  "status": "succeeded",
  "idempotency_key": "unique-key-001",
  "webhook_url": "https://webhook.site/...",
  "failure_reason": null,
  "created_at": "2024-01-01T12:00:00Z",
  "processed_at": "2024-01-01T12:00:04Z"
}
```

### Идемпотентность

Повторный запрос с тем же `Idempotency-Key` вернёт **тот же платёж** без дублирования:

```bash
# Второй запрос с тем же ключом → 202 + тот же payment_id
curl -X POST http://localhost:8000/api/v1/payments \
  -H "Idempotency-Key: unique-key-001" \
  ...
```

## Ключевые решения

| Паттерн | Реализация |
|---|---|
| Outbox | `payments` + `outbox_events` в одной транзакции |
| Polling | `SELECT FOR UPDATE SKIP LOCKED` — безопасен для нескольких экземпляров |
| Идемпотентность | `UNIQUE` индекс на `idempotency_key` + декоратор `@idempotent` |
| DLQ | `x-dead-letter-exchange` на очереди → `payments.dlx` → `payments.dead` |
| Retry webhook | Замыкание `with_retry(attempts=3, backoff=2.0)` |
| Lifecycle | FastAPI `lifespan` + `asyncio.Task` для poller |
| Logging | `structlog` с контекстом `payment_id` в каждой записи |

## Структура проекта

```
app/
  core/         # config.py, logging.py
  domain/       # value_objects.py, events.py, result.py  ← нет infra импортов
  infra/
    db/         # models.py, session.py, repositories.py
    broker/     # publisher.py, topology.py
    gateway/    # emulator.py
    outbox/     # poller.py
    webhook/    # sender.py
  services/     # payments.py  ← бизнес-логика
  api/v1/       # роутеры, схемы, deps
consumer/       # отдельный процесс, не импортирует FastAPI
alembic/        # миграции
```

## Локальная разработка

```bash
# Установить зависимости
pip install poetry && poetry install

# Только инфраструктура
docker-compose up postgres rabbitmq

# Применить миграции
alembic upgrade head

# API
uvicorn app.api.main:app --reload

# Consumer (в другом терминале)
python -m consumer.main
```
