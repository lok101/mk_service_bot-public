from __future__ import annotations

from beartype import beartype


@beartype
class MicromarketStockConcurrencyError(Exception):
    """Raised when optimistic micromarket stock persistence loses a race."""

    def __init__(self, *, machine_code: str) -> None:
        self.machine_code = machine_code
        super().__init__(machine_code)


@beartype
class MicromarketLoadingConcurrencyError(Exception):
    """Raised when optimistic micromarket loading cycle persistence loses a race."""

    def __init__(self, *, machine_code: str) -> None:
        self.machine_code = machine_code
        super().__init__(machine_code)
