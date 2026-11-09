from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.micromarket_loading.move_gateway import (
    MicromarketMoveGateway,
    MoveAlreadyGone,
    MoveDeleteFailed,
)
from src.application.micromarket_loading.ms_catalog_code import resolve_ms_catalog_code
from src.application.micromarket_loading.ports import (
    EnsureOpenVisitTaskPort,
    MicromarketDeviceStockStore,
    MicromarketWarehouseStockSnapshotPort,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.product_identity.ports import DomainProductStore
from src.domain.calendar import operational_day
from src.domain.micromarket_loading.errors import MicromarketLoadingConcurrencyError
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class LoadingDisabled:
    message: str = "загрузка выключена"


@beartype
@dataclass(frozen=True, slots=True)
class LaunchRejected:
    reason: str


@beartype
@dataclass(slots=True)
class LaunchMicromarketLoading:
    cycle_store: MicromarketLoadingCycleStore
    stock_store: MicromarketDeviceStockStore
    gateway: MicromarketMoveGateway
    execute_enabled: bool
    timezone: ZoneInfo
    day_end_hour: int
    clock: Callable[[], datetime]
    warehouse_gate_enabled: bool = True
    products: DomainProductStore | None = None
    ensure_open_visit: EnsureOpenVisitTaskPort | None = None
    warehouse_stock: MicromarketWarehouseStockSnapshotPort | None = None

    @beartype
    def execute(self, *, machine_code: str) -> LoadingDisabled | LaunchRejected | None:
        if not self.execute_enabled:
            _logger.info(
                "micromarket_loading_launch_rejected",
                extra={
                    "machine_code": machine_code,
                    "order_id": None,
                    "reason": "загрузка выключена",
                },
            )
            return LoadingDisabled("загрузка выключена")

        cycle = self.cycle_store.load(machine_code)
        if cycle is None:
            cycle = MicromarketLoadingCycle(machine_code=machine_code)

        if cycle.status is OrderStatus.OPEN:
            _logger.info(
                "micromarket_loading_launch_accepted",
                extra={
                    "machine_code": machine_code,
                    "order_id": cycle.order_id,
                    "reason": "already_open",
                },
            )
            return None

        if cycle.status is OrderStatus.RECOUNTED:
            _logger.info(
                "micromarket_loading_launch_rejected",
                extra={
                    "machine_code": machine_code,
                    "order_id": cycle.order_id,
                    "reason": "order_recounted",
                },
            )
            return LaunchRejected("order_recounted")

        if cycle.status is OrderStatus.CLOSED:
            now = self.clock()
            day = operational_day(now, self.timezone, self.day_end_hour)
            if cycle.opened_operational_day == day:
                _logger.info(
                    "micromarket_loading_launch_rejected",
                    extra={
                        "machine_code": machine_code,
                        "order_id": cycle.order_id,
                        "reason": "order_closed_same_day",
                    },
                )
                return LaunchRejected("order_closed_same_day")

        lines = cycle.lines
        positions: list[tuple[str, Decimal]] = []
        had_positive_launch = False
        catalog_by_line: list[tuple[DraftLine, str]] = []
        for line in lines:
            if line.launch_qty <= 0:
                continue
            had_positive_launch = True
            catalog_code = resolve_ms_catalog_code(self.products, line.product_code)
            if catalog_code is None:
                continue
            catalog_by_line.append((line, catalog_code))
        if self.warehouse_gate_enabled:
            warehouse_by_code: dict[str, Decimal]
            if self.warehouse_stock is not None:
                snapshot = self.warehouse_stock.get()
                if snapshot is None:
                    _logger.info(
                        "micromarket_loading_launch_rejected",
                        extra={
                            "machine_code": machine_code,
                            "order_id": cycle.order_id,
                            "reason": "warehouse_snapshot_missing",
                        },
                    )
                    return LaunchRejected("warehouse_snapshot_missing")
                warehouse_by_code = dict(snapshot.qty_by_catalog_code)
            else:
                catalog_codes = [code for _line, code in catalog_by_line]
                try:
                    warehouse_by_code = dict(
                        self.gateway.warehouse_qty_by_codes(catalog_codes),
                    )
                except Exception as error:
                    _logger.info(
                        "micromarket_loading_launch_rejected",
                        extra={
                            "machine_code": machine_code,
                            "order_id": cycle.order_id,
                            "reason": "warehouse_read_failed",
                        },
                        exc_info=True,
                    )
                    return LaunchRejected(f"warehouse_read_failed: {error}")
            for line, catalog_code in catalog_by_line:
                warehouse_qty = warehouse_by_code.get(catalog_code, Decimal("0"))
                if line.launch_qty > warehouse_qty:
                    _logger.info(
                        "micromarket_loading_launch_rejected",
                        extra={
                            "machine_code": machine_code,
                            "order_id": cycle.order_id,
                            "reason": "launch_qty_above_warehouse",
                        },
                    )
                    return LaunchRejected("launch_qty_above_warehouse")
                positions.append((catalog_code, line.launch_qty))
        else:
            for line, catalog_code in catalog_by_line:
                positions.append((catalog_code, line.launch_qty))

        if not positions:
            reason = "no_catalog_positions" if had_positive_launch else "all_launch_qty_zero"
            _logger.info(
                "micromarket_loading_launch_rejected",
                extra={
                    "machine_code": machine_code,
                    "order_id": cycle.order_id,
                    "reason": reason,
                },
            )
            return LaunchRejected(reason)

        if cycle.order_id is not None and cycle.status is None:
            order_id = cycle.order_id
            if self.gateway.existing_move_for_order_is_stale(
                order_id=order_id,
                now=self.clock(),
            ):
                order_id = str(uuid.uuid4())
                cycle.record_launch_intent(order_id=order_id)
                self.cycle_store.save(cycle)
        else:
            order_id = str(uuid.uuid4())
            cycle.record_launch_intent(order_id=order_id)
            self.cycle_store.save(cycle)

        try:
            move_id = self.gateway.create_move(
                order_id=order_id,
                machine_code=machine_code,
                positions=tuple(positions),
            )
        except Exception as error:
            _logger.info(
                "micromarket_loading_launch_rejected",
                extra={
                    "machine_code": machine_code,
                    "order_id": order_id,
                    "reason": "move_failed",
                },
                exc_info=True,
            )
            return LaunchRejected(f"move_failed: {error}")

        if self.warehouse_stock is not None and positions:
            self.warehouse_stock.apply_delta(
                deltas={code: -qty for code, qty in positions},
            )

        cycle.open_order(
            order_id=order_id,
            move_id=move_id,
            lines=lines,
            opened_at=self.clock(),
            timezone=self.timezone,
            day_end_hour=self.day_end_hour,
        )
        try:
            self.cycle_store.save(cycle)
        except MicromarketLoadingConcurrencyError:
            reloaded = self.cycle_store.load(machine_code)
            if reloaded is not None and reloaded.status is OrderStatus.OPEN:
                if reloaded.move_id != move_id:
                    with contextlib.suppress(MoveAlreadyGone, MoveDeleteFailed):
                        self.gateway.delete_move(move_id=move_id)
                    if self.warehouse_stock is not None and positions:
                        self.warehouse_stock.apply_delta(
                            deltas={code: qty for code, qty in positions},
                        )
                _logger.info(
                    "micromarket_loading_launch_accepted",
                    extra={
                        "machine_code": machine_code,
                        "order_id": reloaded.order_id,
                        "reason": "already_open",
                    },
                )
                return None
            raise
        _logger.info(
            "micromarket_loading_launch_accepted",
            extra={
                "machine_code": machine_code,
                "order_id": order_id,
                "reason": "opened",
            },
        )
        return None
