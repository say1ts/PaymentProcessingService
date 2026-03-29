from __future__ import annotations

import functools
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.events import PaymentCreated
from app.domain.value_objects import Currency, Money
from app.infra.db.models import OutboxEventModel, PaymentModel
from app.infra.db.repositories import (
    get_payment_by_id,
    get_payment_by_idempotency_key,
    insert_outbox_event,
    insert_payment,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class CreatePaymentCommand:
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict
    webhook_url: str
    idempotency_key: str


@dataclass(frozen=True)
class PaymentDTO:
    id: uuid.UUID
    amount: Decimal
    currency: str
    description: str
    metadata: dict
    status: str
    idempotency_key: str
    webhook_url: str
    failure_reason: str | None
    created_at: datetime
    processed_at: datetime | None


def _to_dto(model: PaymentModel) -> PaymentDTO:
    return PaymentDTO(
        id=model.id,
        amount=model.amount,
        currency=model.currency,
        description=model.description,
        metadata=model.metadata_,
        status=model.status,
        idempotency_key=model.idempotency_key,
        webhook_url=model.webhook_url,
        failure_reason=model.failure_reason,
        created_at=model.created_at,
        processed_at=model.processed_at,
    )


def idempotent(func):
    """
    Декоратор-замыкание: проверяем idempotency_key до вставки.
    Ловим IntegrityError (race condition) → возвращаем существующий платёж.
    """
    @functools.wraps(func)
    async def wrapper(session: AsyncSession, cmd: CreatePaymentCommand) -> PaymentDTO:
        existing = await get_payment_by_idempotency_key(session, cmd.idempotency_key)
        if existing:
            log.info(
                "idempotent_hit",
                idempotency_key=cmd.idempotency_key,
                payment_id=str(existing.id),
            )
            return _to_dto(existing)

        try:
            return await func(session, cmd)
        except IntegrityError:
            await session.rollback()
            existing = await get_payment_by_idempotency_key(session, cmd.idempotency_key)
            if existing:
                return _to_dto(existing)
            raise

    return wrapper


@idempotent
async def create_payment(
    session: AsyncSession,
    cmd: CreatePaymentCommand,
) -> PaymentDTO:
    """
    Создаёт платёж и outbox-событие в ОДНОЙ транзакции.
    Outbox-поллер потом заберёт событие и опубликует в RabbitMQ.
    """
    Money.of(cmd.amount, cmd.currency)

    payment_id = uuid.uuid4()
    payment = PaymentModel(
        id=payment_id,
        amount=cmd.amount,
        currency=cmd.currency,
        description=cmd.description,
        metadata_=cmd.metadata,
        status="pending",
        idempotency_key=cmd.idempotency_key,
        webhook_url=cmd.webhook_url,
    )

    event = PaymentCreated(
        payment_id=payment_id,
        webhook_url=cmd.webhook_url,
    )
    outbox = OutboxEventModel(
        id=uuid.uuid4(),
        event_type="payment.created",
        payload={
            "payment_id": str(payment_id),
            "webhook_url": cmd.webhook_url,
            "occurred_at": event.occurred_at.isoformat(),
        },
        status="pending",
    )

    await insert_payment(session, payment)
    await insert_outbox_event(session, outbox)
    await session.commit()

    log.info(
        "payment_created",
        payment_id=str(payment_id),
        amount=str(cmd.amount),
        currency=cmd.currency,
    )

    return _to_dto(payment)


async def get_payment(
    session: AsyncSession,
    payment_id: uuid.UUID,
) -> PaymentDTO | None:
    payment = await get_payment_by_id(session, payment_id)
    if payment is None:
        return None
    return _to_dto(payment)
