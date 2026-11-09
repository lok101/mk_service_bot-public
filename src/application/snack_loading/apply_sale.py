from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from beartype import beartype

from src.application.snack_loading.ports import (
    KitMatrixDeployMapStore,
    SnackMachineStockStore,
)
from src.application.snack_loading.resolve_sale import resolve_snack_sale
from src.domain.machine_sales import MachineSale
from src.domain.snack_loading import SnackMachineStock, SnackStockConcurrencyError

_logger = logging.getLogger(__name__)

_STOCK_SAVE_ATTEMPTS = 3

SnapshotProductLookup = Callable[..., str | None]


@beartype
@dataclass(slots=True)
class ApplySnackSaleToStock:
    stock_store: SnackMachineStockStore
    deploy_map: KitMatrixDeployMapStore
    snapshot_product_lookup: SnapshotProductLookup

    @beartype
    def execute(self, sale: MachineSale) -> MachineSale:
        machine_code = sale.machine_code or ""
        deploy_row = None
        snapshot_product: str | None = None
        if sale.kit_matrix_id is not None:
            mapped = self.deploy_map.get(sale.kit_matrix_id)
            if mapped is not None:
                deploy_row = (mapped.logical_matrix_name, mapped.machine_code)
                if not machine_code:
                    machine_code = mapped.machine_code
                snapshot_product = self.snapshot_product_lookup(
                    machine_code=mapped.machine_code,
                    logical_matrix_name=mapped.logical_matrix_name,
                    line_number=sale.kit_line_number,
                    product_code=sale.product_code,
                )

        status, keys = resolve_snack_sale(
            sale_kind=sale.sale_kind,
            kit_matrix_id=sale.kit_matrix_id,
            machine_code=machine_code,
            kit_line_number=sale.kit_line_number,
            product_code=sale.product_code,
            deploy_map_row=deploy_row,
            snapshot_product=snapshot_product,
        )
        enriched = replace(
            sale,
            machine_code=machine_code or sale.machine_code,
            resolve_status=status,
        )
        if status != "resolved" or keys is None:
            if status in {
                "unresolved_matrix",
                "unresolved_machine",
                "unresolved_line",
                "product_mismatch",
            }:
                _logger.info(
                    "snack_sale_unresolved",
                    extra={
                        "source_id": sale.source_id,
                        "resolve_status": status,
                        "kit_matrix_id": sale.kit_matrix_id,
                        "machine_code": machine_code or None,
                        "kit_line_number": sale.kit_line_number,
                        "product_code": sale.product_code,
                    },
                )
            return enriched

        cell_machine_code, logical_matrix_name, line_number = keys
        for _attempt in range(_STOCK_SAVE_ATTEMPTS):
            stock = self.stock_store.load(cell_machine_code)
            if stock is None:
                stock = SnackMachineStock(machine_code=cell_machine_code)
            stock.apply_sale_deduct(
                source_id=sale.source_id,
                logical_matrix_name=logical_matrix_name,
                line_number=line_number,
                product_code=sale.product_code,
                quantity=sale.quantity,
                occurred_at=sale.occurred_at,
            )
            try:
                self.stock_store.save(stock)
            except SnackStockConcurrencyError:
                continue
            return enriched

        raise SnackStockConcurrencyError(machine_code=cell_machine_code)
