from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.micromarket_loading.ports import MicromarketSaleForReplay


@beartype
@dataclass(frozen=True, slots=True)
class MachineSalesMicromarketSalesAfter:
    """Replay Kit Shop / machine sales after inventory anchor for micromarket Accept."""

    sales_store: MachineSalesStore

    @beartype
    def query(
        self,
        machine_code: str,
        after: datetime,
    ) -> Sequence[MicromarketSaleForReplay]:
        rows: list[MicromarketSaleForReplay] = []
        for sale in self.sales_store.find_after_by_machine_code(machine_code, after=after):
            if sale.resolve_status is not None and sale.resolve_status != "resolved":
                continue
            if sale.sale_kind == "snack":
                continue
            product_code = sale.product_code.strip()
            if not product_code:
                continue
            rows.append(
                MicromarketSaleForReplay(
                    sale_source_id=sale.source_id,
                    product_code=product_code,
                    qty=sale.quantity,
                    occurred_at=sale.occurred_at,
                ),
            )
        return tuple(rows)
