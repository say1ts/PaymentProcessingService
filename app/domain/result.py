from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False


@dataclass(frozen=True)
class Err:
    reason: str

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True


# Удобный тип для аннотаций
type Result[T] = Ok[T] | Err
type GatewayResult = Ok[str] | Err
