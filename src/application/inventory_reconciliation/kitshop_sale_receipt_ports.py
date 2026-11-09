from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class KitShopSaleReceiptStore(Protocol):
    def load(self, sale_id: int) -> dict[str, object] | None: ...

    def save_if_absent(self, *, sale_id: int, payload: dict[str, object]) -> None: ...
