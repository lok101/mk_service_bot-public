"""Ops recovery after mistaken loading rollback: restock device + warehouse snapshot."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.ms_catalog_code import resolve_ms_catalog_code
from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketWarehouseStockSnapshotPort,
)
from src.application.micromarket_loading.restore_historical_loading_move import (
    HistoricalOrderOpenedLookup,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.order import OrderStatus
from src.domain.micromarket_loading.order_events import DraftLine

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class RecoverErroneousRollbackRejected:
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class RecoverErroneousRollbackResult:
    machine_code: str
    order_id: str
    device_stock_applied: bool
    warehouse_delta_lines: int
    domain_closed: bool
    status: str


@beartype
def _launch_lines(lines: tuple[DraftLine, ...]) -> dict[str, Decimal]:
    return {line.product_code: line.launch_qty for line in lines if line.launch_qty > 0}


@beartype
def _warehouse_deltas(
    *,
    lines: tuple[DraftLine, ...],
    products: DomainProductStore | None,
) -> dict[str, Decimal]:
    deltas: dict[str, Decimal] = {}
    for line in lines:
        if line.launch_qty <= 0:
            continue
        catalog_code = resolve_ms_catalog_code(products, line.product_code)
        if catalog_code is None:
            continue
        deltas[catalog_code] = deltas.get(catalog_code, Decimal("0")) - line.launch_qty
    return deltas


@beartype
@dataclass(slots=True)
class RecoverMicromarketLoadingAfterErroneousRollback:
    opened_lookup: HistoricalOrderOpenedLookup
    stock_store: MicromarketDeviceStockStore
    cycle_store: MicromarketLoadingCycleStore | None = None
    warehouse_stock: MicromarketWarehouseStockSnapshotPort | None = None
    products: DomainProductStore | None = None
    now_factory: Callable[[], datetime] = datetime.now

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        order_id: str,
        close_open_cycle: bool = True,
    ) -> RecoverErroneousRollbackResult | RecoverErroneousRollbackRejected:
        opened = self.opened_lookup.find_opened(
            machine_code=machine_code,
            order_id=order_id,
        )
        if opened is None:
            return RecoverErroneousRollbackRejected("order_opened_not_found")

        launch_lines = _launch_lines(opened.lines)
        if not launch_lines:
            return RecoverErroneousRollbackRejected("no_launch_lines")

        stock = self.stock_store.load(machine_code) or MicromarketDeviceStock(
            machine_code=machine_code,
        )
        occurred_at = opened.opened_at
        preview = stock.apply_loading(
            lines=launch_lines,
            loading_run_id=order_id,
            occurred_at=occurred_at,
        )
        if preview is None:
            _logger.info(
                "micromarket_loading_erroneous_rollback_already_recovered",
                extra={"machine_code": machine_code, "order_id": order_id},
            )
            return RecoverErroneousRollbackResult(
                machine_code=machine_code,
                order_id=order_id,
                device_stock_applied=False,
                warehouse_delta_lines=0,
                domain_closed=False,
                status="already_recovered",
            )

        warehouse_deltas = _warehouse_deltas(lines=opened.lines, products=self.products)
        if self.warehouse_stock is not None and warehouse_deltas:
            self.warehouse_stock.apply_delta(deltas=warehouse_deltas)

        self.stock_store.save(stock)

        domain_closed = False
        if close_open_cycle and self.cycle_store is not None:
            cycle = self.cycle_store.load(machine_code)
            if (
                cycle is not None
                and cycle.status is OrderStatus.OPEN
                and cycle.order_id == order_id
            ):
                cycle.close_without_recount(at=self.now_factory())
                self.cycle_store.save(cycle)
                domain_closed = True

        _logger.info(
            "micromarket_loading_erroneous_rollback_recovered",
            extra={
                "machine_code": machine_code,
                "order_id": order_id,
                "device_lines": len(launch_lines),
                "warehouse_lines": len(warehouse_deltas),
                "domain_closed": domain_closed,
            },
        )
        return RecoverErroneousRollbackResult(
            machine_code=machine_code,
            order_id=order_id,
            device_stock_applied=True,
            warehouse_delta_lines=len(warehouse_deltas),
            domain_closed=domain_closed,
            status="recovered",
        )
