from __future__ import annotations

import asyncio
from contextlib import suppress

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.logging import get_logger
from app.infra.broker.publisher import RabbitMQPublisher
from app.infra.db.repositories import (
    get_pending_outbox_events,
    mark_outbox_failed,
    mark_outbox_published,
)

log = get_logger(__name__)


class OutboxPoller:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        publisher: RabbitMQPublisher,
        poll_interval: float = 1.0,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop(), name="outbox-poller")
        log.info("outbox_poller_started", interval=self._poll_interval)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        log.info("outbox_poller_stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._process_pending()
            except Exception:
                log.exception("outbox_poll_iteration_error")
            await asyncio.sleep(self._poll_interval)

    async def _process_pending(self) -> None:
        async with self._session_factory() as session:
            events = await get_pending_outbox_events(session, limit=10)
            if not events:
                return

            log.debug("outbox_processing_batch", count=len(events))

            for event in events:
                try:
                    await self._publisher.publish(event)
                    await mark_outbox_published(session, event.id)
                    await session.commit()
                    log.info(
                        "outbox_event_forwarded",
                        event_id=str(event.id),
                        event_type=event.event_type,
                    )
                except Exception as exc:
                    await session.rollback()
                    log.error("outbox_event_publish_failed", event_id=str(event.id), error=str(exc))
                
                    # Изолированная попытка пометить как failed в отдельной транзакции
                    try:
                        async with self._session_factory() as fail_session:
                            await mark_outbox_failed(fail_session, event.id)
                            await fail_session.commit()
                    except Exception:
                        log.exception("critical_error_marking_outbox_failed", event_id=str(event.id))
