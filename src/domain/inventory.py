from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class InventoryPosition:
    product_code: str
    quantity: float | int

    def __post_init__(self) -> None:
        if not self.product_code:
            raise ValueError("InventoryPosition product_code must not be empty")
