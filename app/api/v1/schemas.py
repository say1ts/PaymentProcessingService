from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.domain.value_objects import Currency


class CreatePaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0, description="Сумма платежа (> 0)")
    currency: Currency
    description: str = Field(min_length=1, max_length=500)
    metadata: dict = Field(default_factory=dict)
    webhook_url: AnyHttpUrl

    @field_validator("amount")
    @classmethod
    def quantize_amount(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))


class CreatePaymentResponse(BaseModel):
    payment_id: uuid.UUID
    status: str
    created_at: datetime


class PaymentResponse(BaseModel):
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

    model_config = {"from_attributes": True}
