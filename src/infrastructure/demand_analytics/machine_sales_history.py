from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.demand_analytics import SalesHistoryReadFailed
from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.domain.ids import MachineId


@beartype
class MachineSalesHistory:
    """SKU quantities from ``MachineSalesStore`` for one machine and window."""

    def __init__(self, store: MachineSalesStore) -> None:
        self._store = store

    @beartype
    def list_quantities(
        self,
        *,
        machine_id: str,
        product_code: str,
        opened_at: datetime,
        closed_at: datetime,
        sale_kind: str | None = None,
    ) -> tuple[tuple[datetime, Decimal], ...] | SalesHistoryReadFailed:
        try:
            sales = self._store.find_in_window(
                MachineId(machine_id),
                opened_at=opened_at,
                closed_at=closed_at,
            )
        except Exception:
            return SalesHistoryReadFailed()
        rows: list[tuple[datetime, Decimal]] = []
        for sale in sales:
            if sale.product_code != product_code:
                continue
            if sale_kind is not None and sale.sale_kind != sale_kind:
                continue
            rows.append((sale.occurred_at, sale.quantity))
        return tuple(rows)
