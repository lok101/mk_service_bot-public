from __future__ import annotations

from datetime import timedelta

from beartype import beartype


class NonRetryableOutboxError(Exception):
    """Outbox side effect cannot succeed without manual intervention."""


class DeferredRetryOutboxError(Exception):
    """Transient outbox failure with handler-specified retry delay."""

    @beartype
    def __init__(
        self,
        message: str,
        *,
        delay: timedelta,
        max_attempts: int | None = None,
    ) -> None:
        self.delay = delay
        self.max_attempts = max_attempts
        super().__init__(message)


class UnknownProductNamesError(NonRetryableOutboxError):
    @beartype
    def __init__(self, product_names: tuple[str, ...]) -> None:
        if not product_names:
            raise ValueError("product_names must not be empty")
        self.product_names = product_names
        joined = ", ".join(product_names)
        super().__init__(
            f"В каталоге товаров не найдены позиции: {joined}. "
            "Добавьте их в таблицу каталога и повторите обработку записи outbox.",
        )


class FormQuantityValidationError(NonRetryableOutboxError):
    @beartype
    def __init__(self, message: str) -> None:
        if not message:
            raise ValueError("message must not be empty")
        super().__init__(message)
