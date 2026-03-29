from __future__ import annotations

import json

import aio_pika
import aio_pika.abc

from app.core.logging import get_logger
from app.infra.db.models import OutboxEventModel

log = get_logger(__name__)

EXCHANGE_NAME = "payments.exchange"
ROUTING_KEY = "payment.created"


class RabbitMQPublisher:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    async def __aenter__(self) -> RabbitMQPublisher:
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        
        self._exchange = await self._channel.declare_exchange(
            EXCHANGE_NAME,
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        log.info("rabbitmq_publisher_connected", exchange=EXCHANGE_NAME)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        log.info("rabbitmq_publisher_disconnected")

    async def publish(self, event: OutboxEventModel) -> None:
        if self._exchange is None:
            raise RuntimeError("Publisher not started. Use `async with RabbitMQPublisher(...)`")

        body = json.dumps(event.payload).encode()
        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(event.id),
        )
        await self._exchange.publish(message, routing_key=ROUTING_KEY)
        log.debug(
            "outbox_event_published",
            event_id=str(event.id),
            event_type=event.event_type,
        )
