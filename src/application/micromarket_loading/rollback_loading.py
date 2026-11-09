from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.move_gateway import (
    MicromarketMoveGateway,
    MoveAlreadyGone,
)
from src.application.micromarket_loading.ms_catalog_code import resolve_ms_catalog_code
from src.application.micromarket_loading.ports import (
    DetachVisitTaskOnLoadingRollbackPort,
    MicromarketWarehouseStockSnapshotPort,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading.order import OrderStatus

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class RollbackNotAllowed:
    reason: str = "order_not_open"


@beartype
@dataclass(slots=True)
class RollbackMicromarketLoading:
    cycle_store: MicromarketLoadingCycleStore
    gateway: MicromarketMoveGateway
    clock: Callable[[], datetime]
    detach_visit: DetachVisitTaskOnLoadingRollbackPort | None = None
    warehouse_stock: MicromarketWarehouseStockSnapshotPort | None = None
    products: DomainProductStore | None = None

    @beartype
    def execute(self, *, machine_code: str) -> RollbackNotAllowed | None:
        cycle = self.cycle_store.load(machine_code)
        if cycle is None or cycle.status is not OrderStatus.OPEN:
            _logger.info(
                "micromarket_loading_rollback",
                extra={
                    "machine_code": machine_code,
                    "order_id": None if cycle is None else cycle.order_id,
                    "reason": "order_not_open",
                },
            )
            return RollbackNotAllowed()

        move_id = cycle.move_id
        if move_id is None:
            raise ValueError("open order requires move_id")

        restore_deltas: dict[str, Decimal] = {}
        if self.warehouse_stock is not None:
            for line in cycle.lines:
                if line.launch_qty <= 0:
                    continue
                catalog_code = resolve_ms_catalog_code(self.products, line.product_code)
                if catalog_code is None:
                    continue
                restore_deltas[catalog_code] = (
                    restore_deltas.get(catalog_code, Decimal("0")) + line.launch_qty
                )

        visit_id = cycle.visit_id
        delete_ms_move = True
        if cycle.opened_at is not None:
            move_moment = self.gateway.move_moment(move_id=move_id)
            if move_moment is not None and move_moment < cycle.opened_at - timedelta(seconds=60):
                delete_ms_move = False
                _logger.warning(
                    "micromarket_loading_rollback_skip_historical_move",
                    extra={
                        "machine_code": machine_code,
                        "order_id": cycle.order_id,
                        "move_id": move_id,
                        "opened_at": cycle.opened_at.isoformat(),
                        "move_moment": move_moment.isoformat(),
                    },
                )
        if delete_ms_move:
            with contextlib.suppress(MoveAlreadyGone):
                self.gateway.delete_move(move_id=move_id)

        if self.warehouse_stock is not None and restore_deltas:
            self.warehouse_stock.apply_delta(deltas=restore_deltas)

        at = self.clock()
        cycle.roll_back(at=at)
        self.cycle_store.save(cycle)
        if self.detach_visit is not None:
            self.detach_visit.detach(
                machine_code=machine_code,
                at=at,
                visit_id=visit_id,
            )
        _logger.info(
            "micromarket_loading_rollback",
            extra={
                "machine_code": machine_code,
                "order_id": cycle.order_id,
                "visit_id": visit_id,
            },
        )
        return None
