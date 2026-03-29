from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.models import OutboxEventModel, PaymentModel


async def get_payment_by_id(
    session: AsyncSession,
    payment_id: uuid.UUID,
) -> PaymentModel | None:
    return await session.get(PaymentModel, payment_id)


async def get_payment_by_idempotency_key(
    session: AsyncSession,
    idempotency_key: str,
) -> PaymentModel | None:
    stmt = select(PaymentModel).where(PaymentModel.idempotency_key == idempotency_key)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def insert_payment(session: AsyncSession, payment: PaymentModel) -> None:
    """Добавляет payment в сессию. Коммит — на вызывающей стороне."""
    session.add(payment)
    await session.flush()


async def update_payment_status(
    session: AsyncSession,
    payment_id: uuid.UUID,
    status: str,
    failure_reason: str | None = None,
) -> None:
    values: dict = {
        "status": status,
        "processed_at": datetime.now(UTC),
    }
    if failure_reason is not None:
        values["failure_reason"] = failure_reason

    stmt = (
        update(PaymentModel)
        .where(PaymentModel.id == payment_id)
        .values(**values)
    )
    await session.execute(stmt)


async def increment_consumer_attempts(
    session: AsyncSession,
    payment_id: uuid.UUID,
) -> int:
    """
    Атомарно инкрементирует consumer_attempts и возвращает новое значение.
    Коммит вызывается внутри — операция должна быть изолирована от основной транзакции.
    """
    stmt = (
        update(PaymentModel)
        .where(PaymentModel.id == payment_id)
        .values(consumer_attempts=PaymentModel.consumer_attempts + 1)
        .returning(PaymentModel.consumer_attempts)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()


async def insert_outbox_event(session: AsyncSession, event: OutboxEventModel) -> None:
    """Добавляет outbox-событие в сессию. Коммит — на вызывающей стороне."""
    session.add(event)
    await session.flush()


async def get_pending_outbox_events(
    session: AsyncSession,
    limit: int = 10,
) -> list[OutboxEventModel]:
    """
    SELECT FOR UPDATE SKIP LOCKED — атомарно захватываем строки.
    Если поллер запущен в нескольких экземплярах, они не дерутся за одни события.
    """
    stmt = (
        select(OutboxEventModel)
        .where(OutboxEventModel.status == "pending")
        .order_by(OutboxEventModel.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_outbox_published(session: AsyncSession, event_id: uuid.UUID) -> None:
    stmt = (
        update(OutboxEventModel)
        .where(OutboxEventModel.id == event_id)
        .values(
            status="published",
            published_at=datetime.now(UTC),
        )
    )
    await session.execute(stmt)


async def mark_outbox_failed(session: AsyncSession, event_id: uuid.UUID) -> None:
    """Инкрементируем attempts; если >= 3 — помечаем failed."""
    stmt = (
        update(OutboxEventModel)
        .where(OutboxEventModel.id == event_id)
        .values(attempts=OutboxEventModel.attempts + 1)
        .returning(OutboxEventModel.attempts)
    )
    result = await session.execute(stmt)
    attempts = result.scalar_one()

    if attempts >= 3:
        await session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == event_id)
            .values(status="failed")
        )
        