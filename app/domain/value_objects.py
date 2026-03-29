from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if self.amount <= Decimal("0"):
            raise ValueError(f"Amount must be positive, got {self.amount}")

    @classmethod
    def of(cls, amount: str | int | float | Decimal, currency: str | Currency) -> "Money":
        try:
            decimal_amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise ValueError(f"Invalid amount: {amount}")
        return cls(
            amount=decimal_amount,
            currency=Currency(currency),
        )

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
