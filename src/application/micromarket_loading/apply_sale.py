from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.application.master_data import MachineKind
from src.application.micromarket_loading.ports import (
    MachineKindLookup,
    MicromarketDeviceStockStore,
)
from src.domain.micromarket_loading import MicromarketDeviceStock, MicromarketStockConcurrencyError

_logger = logging.getLogger(__name__)

_STOCK_SAVE_ATTEMPTS = 3

ApplyMicromarketSaleStatus = Literal[
    "deducted",
    "idempotent_skip",
    "skipped_non_micromarket",
    "skipped_no_machine_code",
]


@beartype
@dataclass(frozen=True, slots=True)
class ApplyMicromarketSaleResult:
    status: ApplyMicromarketSaleStatus


@beartype
@dataclass(slots=True)
class ApplyMicromarketSaleToStock:
    stock_store: MicromarketDeviceStockStore
    machine_kind_lookup: MachineKindLookup

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        product_code: str,
        qty: Decimal,
        sale_source_id: str,
        occurred_at: datetime,
    ) -> ApplyMicromarketSaleResult:
        if not machine_code.strip():
            _logger.info(
                "micromarket_sale_unresolved_machine_code",
                extra={"sale_source_id": sale_source_id, "product_code": product_code},
            )
            return ApplyMicromarketSaleResult(status="skipped_no_machine_code")

        kind = self.machine_kind_lookup.kind_of(machine_code)
        if kind is not MachineKind.MICRO_MARKET:
            _logger.info(
                "micromarket_sale_skipped_non_micromarket",
                extra={
                    "sale_source_id": sale_source_id,
                    "machine_code": machine_code,
                    "kind": None if kind is None else kind.value,
                },
            )
            return ApplyMicromarketSaleResult(status="skipped_non_micromarket")

        for _attempt in range(_STOCK_SAVE_ATTEMPTS):
            stock = self.stock_store.load(machine_code)
            if stock is None:
                stock = MicromarketDeviceStock(machine_code=machine_code)

            if stock.has_seen_sale_source_id(sale_source_id):
                return ApplyMicromarketSaleResult(status="idempotent_skip")

            stock.apply_sale_deduct(
                sale_source_id=sale_source_id,
                product_code=product_code,
                qty=qty,
                occurred_at=occurred_at,
            )
            try:
                self.stock_store.save(stock)
            except MicromarketStockConcurrencyError:
                continue
            _logger.info(
                "micromarket_sale_deducted",
                extra={
                    "sale_source_id": sale_source_id,
                    "machine_code": machine_code,
                    "product_code": product_code,
                    "qty": str(qty),
                },
            )
            return ApplyMicromarketSaleResult(status="deducted")

        raise MicromarketStockConcurrencyError(machine_code=machine_code)
