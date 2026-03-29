from __future__ import annotations

import uuid
from datetime import UTC, datetime

from faststream.rabbit import RabbitMessage
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.logging import get_logger
from app.domain.result import Err, Ok
from app.infra.db.repositories import get_payment_by_id, update_payment_status
from app.infra.gateway.emulator import GatewayEmulator
from app.infra.webhook.sender import send_webhook

log = get_logger(__name__)


async def process_payment_message(
    body: dict,
    msg: RabbitMessage,
    session_factory: async_sessionmaker,
    gateway: GatewayEmulator,
) -> None:
    payment_id_str: str = body["payment_id"]
    webhook_url: str = body["webhook_url"]

    x_death = msg.headers.get("x-death", [])
    delivery_count = x_death[0].get("count", 0) if x_death else 0

    log.info("consumer_received", payment_id=payment_id_str, attempt=delivery_count + 1)

    payment_id = uuid.UUID(payment_id_str)

    try:
        async with session_factory() as session:
            payment = await get_payment_by_id(session, payment_id)

            if payment is None:
                log.error("consumer_payment_not_found", payment_id=payment_id_str)
                await msg.ack()
                return

            if payment.status == "pending":
                result = await gateway(payment)
                match result:
                    case Ok(transaction_id):
                        await update_payment_status(session, payment_id, "succeeded")
                        await session.commit()
                        webhook_payload = _build_success_payload(payment_id, transaction_id)
                    case Err(reason):
                        await update_payment_status(session, payment_id, "failed", failure_reason=reason)
                        await session.commit()
                        webhook_payload = _build_failure_payload(payment_id, reason)
            else:
                if payment.status == "succeeded":
                    webhook_payload = _build_success_payload(payment_id, "ALREADY_PROCESSED")
                else:
                    webhook_payload = _build_failure_payload(payment_id, "ALREADY_PROCESSED")

        await send_webhook(webhook_url, webhook_payload)
        await msg.ack()

    except Exception as exc:
        if delivery_count < 2:
            log.warning("consumer_retry", payment_id=payment_id_str, attempt=delivery_count + 1)
            await msg.nack(requeue=True)
        else:
            log.error("consumer_to_dlq", payment_id=payment_id_str, error=str(exc))
            await msg.nack(requeue=False)


def _build_success_payload(payment_id: uuid.UUID, transaction_id: str) -> dict:
    return {
        "event": "payment.succeeded",
        "payment_id": str(payment_id),
        "transaction_id": transaction_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _build_failure_payload(payment_id: uuid.UUID, reason: str) -> dict:
    return {
        "event": "payment.failed",
        "payment_id": str(payment_id),
        "failure_reason": reason,
        "timestamp": datetime.now(UTC).isoformat(),
    }
