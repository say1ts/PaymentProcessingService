from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aio_pika
from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitMessage

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.infra.broker.topology import payments_exchange, payments_queue
from app.infra.db.session import async_session_factory, engine
from app.infra.gateway.emulator import GatewayEmulator
from consumer.handler import process_payment_message

log = get_logger(__name__)

broker = RabbitBroker(url=settings.rabbitmq_url)


async def _declare_topology() -> None:
    """
    Объявляем топологию RabbitMQ через aio-pika напрямую.

    FastStream объявляет очереди/exchanges лениво при старте subscriber-а,
    но не умеет корректно привязывать DLQ к DLX. Поэтому используем aio-pika
    для явного объявления до старта брокера.
    """
    conn = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with conn:
        channel = await conn.channel()
        dlx = await channel.declare_exchange(
            "payments.dlx",
            aio_pika.ExchangeType.FANOUT,
            durable=True,
        )

        dead_q = await channel.declare_queue("payments.dead", durable=True)
        await dead_q.bind(dlx)

        payments_ex = await channel.declare_exchange(
            "payments.exchange",
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        main_q = await channel.declare_queue(
            "payments.new",
            durable=True,
            arguments={"x-dead-letter-exchange": "payments.dlx"},
        )
        await main_q.bind(payments_ex, routing_key="payment.created")

    log.info("rabbitmq_topology_declared")


@asynccontextmanager
async def lifespan(app: FastStream | None = None) -> AsyncGenerator[None]:
    setup_logging()
    log.info("consumer_starting")

    # Сначала объявляем топологию, потом подключаем брокер FastStream
    await _declare_topology()
    await broker.connect()

    log.info("consumer_started")
    yield

    from app.infra.webhook.sender import _client
    await _client.aclose()
    await engine.dispose()
    log.info("consumer_stopped")


app = FastStream(broker, lifespan=lifespan)

_gateway = GatewayEmulator(
    success_rate=settings.gateway_success_rate,
    min_delay=settings.gateway_min_delay,
    max_delay=settings.gateway_max_delay,
)


@broker.subscriber(payments_queue, exchange=payments_exchange)
async def on_payment_created(body: dict, msg: RabbitMessage) -> None:
    await process_payment_message(
        body=body,
        msg=msg,
        session_factory=async_session_factory,
        gateway=_gateway,
    )


if __name__ == "__main__":
    asyncio.run(app.run())