from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitMessage

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.infra.broker.topology import (
    dead_queue,
    dlx,
    payments_exchange,
    payments_queue,
)
from app.infra.db.session import async_session_factory, engine
from app.infra.gateway.emulator import GatewayEmulator
from consumer.handler import process_payment_message

log = get_logger(__name__)

broker = RabbitBroker(url=settings.rabbitmq_url)


@asynccontextmanager
async def lifespan(app: FastStream | None = None) -> AsyncGenerator[None]:
    setup_logging()
    log.info("consumer_starting")

    await broker.connect()
    async with broker:
        await broker.declare_exchange(dlx)
        await broker.declare_queue(dead_queue)
        await broker.declare_exchange(payments_exchange)
        await broker.declare_queue(payments_queue)

    log.info("consumer_topology_declared")
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
