from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.application.snack_loading.ports import SnackMachineStockStore, SnackSalesAfterPort
from src.domain.snack_loading import SnackMachineStock, SnackStockConcurrencyError
from src.domain.snack_loading.events import CellKey

SnackInventoryMode = Literal["now", "as_of"]

_STOCK_SAVE_ATTEMPTS = 3


@beartype
@dataclass(slots=True)
class AcceptSnackInventory:
    stock_store: SnackMachineStockStore
    sales_after: SnackSalesAfterPort

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        mode: SnackInventoryMode,
        as_of: datetime | None,
        submitted_at: datetime,
        quantities: Mapping[CellKey, Decimal],
        product_by_key: Mapping[CellKey, str],
        inventory_id: str,
    ) -> None:
        if mode == "now":
            anchor = submitted_at
        else:
            if as_of is None:
                raise ValueError("as_of is required for snack inventory mode as_of")
            anchor = as_of

        for _attempt in range(_STOCK_SAVE_ATTEMPTS):
            stock = self.stock_store.load(machine_code)
            if stock is None:
                stock = SnackMachineStock(machine_code=machine_code)

            stock.apply_inventory(
                as_of=anchor,
                quantities=quantities,
                product_by_key=product_by_key,
                inventory_id=inventory_id,
            )

            affected_cells = set(quantities)
            for sale in self.sales_after.query(machine_code, anchor):
                if sale.resolve_status != "resolved":
                    continue
                cell_key: CellKey = (
                    machine_code,
                    sale.logical_matrix_name,
                    sale.line_number,
                )
                if cell_key not in affected_cells:
                    continue
                if sale.occurred_at <= anchor:
                    continue
                stock.apply_sale_deduct(
                    source_id=sale.source_id,
                    logical_matrix_name=sale.logical_matrix_name,
                    line_number=sale.line_number,
                    product_code=sale.product_code,
                    quantity=sale.quantity,
                    occurred_at=sale.occurred_at,
                )

            try:
                self.stock_store.save(stock)
            except SnackStockConcurrencyError:
                continue
            return

        raise SnackStockConcurrencyError(machine_code=machine_code)
