from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.sale_skip import MachineSaleSkip


@runtime_checkable
class MachineSaleSkipStore(Protocol):
    @beartype
    def upsert(self, skip: MachineSaleSkip) -> None: ...

    @beartype
    def get(self, source_id: str) -> MachineSaleSkip | None: ...

    @beartype
    def delete_by_source_id(self, source_id: str) -> bool: ...
