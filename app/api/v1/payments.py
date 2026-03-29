from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import ApiKeyDep, SessionDep
from app.api.v1.schemas import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    PaymentResponse,
)
from app.domain.value_objects import Currency
from app.services.payments import CreatePaymentCommand, create_payment, get_payment

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreatePaymentResponse,
    summary="Создать платёж",
)
async def create_payment_endpoint(
    body: CreatePaymentRequest,
    session: SessionDep,
    _: ApiKeyDep,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> CreatePaymentResponse:
    cmd = CreatePaymentCommand(
        amount=body.amount,
        currency=Currency(body.currency),
        description=body.description,
        metadata=body.metadata,
        webhook_url=str(body.webhook_url),
        idempotency_key=idempotency_key,
    )
    dto = await create_payment(session, cmd)
    return CreatePaymentResponse(
        payment_id=dto.id,
        status=dto.status,
        created_at=dto.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    summary="Получить платёж по ID",
)
async def get_payment_endpoint(
    payment_id: uuid.UUID,
    session: SessionDep,
    _: ApiKeyDep,
) -> PaymentResponse:
    dto = await get_payment(session, payment_id)
    if dto is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found",
        )
    return PaymentResponse(
        id=dto.id,
        amount=dto.amount,
        currency=dto.currency,
        description=dto.description,
        metadata=dto.metadata,
        status=dto.status,
        idempotency_key=dto.idempotency_key,
        webhook_url=dto.webhook_url,
        failure_reason=dto.failure_reason,
        created_at=dto.created_at,
        processed_at=dto.processed_at,
    )
