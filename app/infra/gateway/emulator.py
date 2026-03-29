import asyncio
import random
import uuid

from app.core.logging import get_logger
from app.domain.result import Err, GatewayResult, Ok
from app.infra.db.models import PaymentModel

log = get_logger(__name__)


class GatewayEmulator:
    def __init__(
        self,
        success_rate: float = 0.9,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
    ) -> None:
        if not 0.0 <= success_rate <= 1.0:
            raise ValueError(f"success_rate must be in [0, 1], got {success_rate}")
        self._success_rate = success_rate
        self._min_delay = min_delay
        self._max_delay = max_delay

    async def __call__(self, payment: PaymentModel) -> GatewayResult:
        """Эмулирует обработку платежа: задержка + случайный исход."""
        delay = random.uniform(self._min_delay, self._max_delay)
        await asyncio.sleep(delay)

        if random.random() < self._success_rate:
            transaction_id = f"tx_{uuid.uuid4().hex[:16]}"
            log.info(
                "gateway_success",
                payment_id=str(payment.id),
                transaction_id=transaction_id,
                delay=round(delay, 2),
            )
            return Ok(transaction_id)

        reason = "Insufficient funds"
        log.info(
            "gateway_failure",
            payment_id=str(payment.id),
            reason=reason,
            delay=round(delay, 2),
        )
        return Err(reason)
