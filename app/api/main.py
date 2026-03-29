from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1.router import v1_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.infra.broker.publisher import RabbitMQPublisher
from app.infra.db.session import async_session_factory, engine
from app.infra.outbox.poller import OutboxPoller

log = get_logger(__name__)

_publisher: RabbitMQPublisher | None = None
_poller: OutboxPoller | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    global _publisher, _poller

    setup_logging()
    log.info("app_starting", environment=settings.environment)

    _publisher = RabbitMQPublisher(url=settings.rabbitmq_url)
    await _publisher.__aenter__()

    _poller = OutboxPoller(
        session_factory=async_session_factory,
        publisher=_publisher,
        poll_interval=settings.outbox_poll_interval,
    )
    await _poller.start()
    
    log.info("app_started")
    yield


    log.info("app_stopping")
    await _poller.stop()
    await _publisher.__aexit__(None, None, None)
    await engine.dispose()
    log.info("app_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Payment Processing Service",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(v1_router)

    @app.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        try:
            async with engine.connect() as conn:
                await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            return JSONResponse({"status": "ok"})
        except Exception as exc:
            log.error("healthcheck_failed", error=str(exc))
            return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)

    return app


app = create_app()
