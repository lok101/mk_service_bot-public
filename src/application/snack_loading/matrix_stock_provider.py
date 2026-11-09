from __future__ import annotations

import logging
from dataclasses import dataclass

from beartype import beartype

from src.application.snack_loading.ports import SnackMachineStockStore

_logger = logging.getLogger(__name__)


@beartype
@dataclass(slots=True)
class DomainMatrixStockProvider:
    store: SnackMachineStockStore

    @beartype
    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None:
        try:
            stock = self.store.load(machine_code)
            if stock is None:
                return None
            cell_product = stock.product(machine_code, logical_matrix_name, line_number)
            if cell_product != product_code:
                return None
            qty = stock.qty(machine_code, logical_matrix_name, line_number)
            if qty < 0 or qty != qty.to_integral_value():
                _logger.warning(
                    "matrix_stock_invalid",
                    extra={
                        "machine_code": machine_code,
                        "logical_matrix_name": logical_matrix_name,
                        "line_number": line_number,
                        "product_code": product_code,
                        "raw_stock": str(qty),
                    },
                )
                return None
            return int(qty)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "matrix_stock_fetch_failed",
                extra={
                    "machine_code": machine_code,
                    "logical_matrix_name": logical_matrix_name,
                    "line_number": line_number,
                    "product_code": product_code,
                    "error": str(exc),
                },
            )
            return None
