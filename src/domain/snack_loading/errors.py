from __future__ import annotations

from beartype import beartype


@beartype
class SnackStockConcurrencyError(Exception):
    """Raised when optimistic snack machine stock persistence loses a race."""

    def __init__(self, *, machine_code: str) -> None:
        self.machine_code = machine_code
        super().__init__(machine_code)
