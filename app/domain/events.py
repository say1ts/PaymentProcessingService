from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DomainEvent:
    """Базовый класс для всех доменных событий."""
    occurred_at: datetime = field(default_factory=_now, compare=False)


@dataclass(frozen=True, kw_only=True)
class PaymentCreated(DomainEvent):
    payment_id: UUID
    webhook_url: str


@dataclass(frozen=True, kw_only=True)
class PaymentSucceeded(DomainEvent):
    payment_id: UUID
    webhook_url: str


@dataclass(frozen=True, kw_only=True)
class PaymentFailed(DomainEvent):
    payment_id: UUID
    webhook_url: str
    reason: str
