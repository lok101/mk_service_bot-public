from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.micromarket_loading.assembly_reservation import available_for_code
from src.application.micromarket_loading.launch_loading import (
    LaunchRejected,
    LoadingDisabled,
)
from src.application.micromarket_loading.ports import (
    MicromarketAssemblyOrderStore,
    MicromarketWarehouseStockSnapshotPort,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.domain.micromarket_loading.assembly_order import (
    AssemblyOrderStatus,
    DuplicateCatalogCode,
    InvalidAssemblyOrderTransition,
    MicromarketAssemblyOrder,
    MicromarketAssemblyOrderLine,
    find_duplicate_on_machine,
)
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class MicromarketLoadingLauncher(Protocol):
    def execute(
        self,
        *,
        machine_code: str,
    ) -> None | LoadingDisabled | LaunchRejected: ...


@beartype
@dataclass(frozen=True, slots=True)
class AssemblyOrderRejected:
    reason: str
    targets: tuple[str, ...] = ()


@beartype
@dataclass(slots=True)
class ManageMicromarketAssemblyOrders:
    store: MicromarketAssemblyOrderStore
    warehouse_stock: MicromarketWarehouseStockSnapshotPort | None
    clock: Callable[[], datetime]

    @beartype
    def list_open_for_machine(self, *, machine_code: str) -> tuple[MicromarketAssemblyOrder, ...]:
        return self.store.list_open_for_machine(machine_code)

    @beartype
    def create(
        self,
        *,
        machine_code: str,
        lines: Mapping[str, Decimal],
    ) -> MicromarketAssemblyOrder | AssemblyOrderRejected | DuplicateCatalogCode:
        parsed = _parse_lines(lines)
        if isinstance(parsed, AssemblyOrderRejected):
            return parsed
        open_all = self.store.list_open()
        dup = find_duplicate_on_machine(
            machine_code=machine_code,
            candidate_codes=tuple(line.catalog_code for line in parsed),
            open_orders=open_all,
        )
        if dup is not None:
            return dup
        shortage = self._shortage_against_available(parsed, open_all)
        if shortage is not None:
            return shortage
        order = MicromarketAssemblyOrder(
            order_id=str(uuid.uuid4()),
            machine_code=machine_code.strip(),
            lines=parsed,
            created_at=self.clock(),
        )
        self.store.save(order)
        _LOGGER.info(
            "micromarket_assembly_order_created",
            extra={"machine_code": machine_code, "order_id": order.order_id},
        )
        return order

    @beartype
    def update(
        self,
        *,
        order_id: str,
        lines: Mapping[str, Decimal],
    ) -> (
        MicromarketAssemblyOrder
        | AssemblyOrderRejected
        | DuplicateCatalogCode
        | InvalidAssemblyOrderTransition
    ):
        current = self.store.get(order_id)
        if current is None:
            return AssemblyOrderRejected("order_not_found")
        if current.status is not AssemblyOrderStatus.OPEN:
            return AssemblyOrderRejected("order_not_open")
        parsed = _parse_lines(lines)
        if isinstance(parsed, AssemblyOrderRejected):
            return parsed
        open_all = self.store.list_open()
        dup = find_duplicate_on_machine(
            machine_code=current.machine_code,
            candidate_codes=tuple(line.catalog_code for line in parsed),
            open_orders=open_all,
            exclude_order_id=order_id,
        )
        if dup is not None:
            return dup
        others = tuple(o for o in open_all if o.order_id != order_id)
        shortage = self._shortage_against_available(parsed, others)
        if shortage is not None:
            return shortage
        updated = current.with_lines(parsed)
        if isinstance(updated, InvalidAssemblyOrderTransition):
            return updated
        self.store.save(updated)
        _LOGGER.info(
            "micromarket_assembly_order_updated",
            extra={"machine_code": current.machine_code, "order_id": order_id},
        )
        return updated

    @beartype
    def cancel(
        self,
        *,
        order_id: str,
    ) -> MicromarketAssemblyOrder | AssemblyOrderRejected | InvalidAssemblyOrderTransition:
        current = self.store.get(order_id)
        if current is None:
            return AssemblyOrderRejected("order_not_found")
        cancelled = current.cancel()
        if isinstance(cancelled, InvalidAssemblyOrderTransition):
            return cancelled
        self.store.save(cancelled)
        _LOGGER.info(
            "micromarket_assembly_order_cancelled",
            extra={"machine_code": current.machine_code, "order_id": order_id},
        )
        return cancelled

    @beartype
    def _shortage_against_available(
        self,
        lines: tuple[MicromarketAssemblyOrderLine, ...],
        open_orders: tuple[MicromarketAssemblyOrder, ...],
    ) -> AssemblyOrderRejected | None:
        snapshot = None if self.warehouse_stock is None else self.warehouse_stock.get()
        offenders: list[str] = []
        for line in lines:
            available = available_for_code(
                snapshot=snapshot,
                open_orders=open_orders,
                catalog_code=line.catalog_code,
            )
            if line.qty > available:
                offenders.append(line.catalog_code)
        if offenders:
            return AssemblyOrderRejected(
                "qty_above_available",
                targets=tuple(sorted(set(offenders))),
            )
        return None


@beartype
@dataclass(slots=True)
class LaunchFromAssemblyOrders:
    assembly_store: MicromarketAssemblyOrderStore
    cycle_store: MicromarketLoadingCycleStore
    warehouse_stock: MicromarketWarehouseStockSnapshotPort | None
    launch: MicromarketLoadingLauncher

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        actor: str = "curator",
    ) -> None | LoadingDisabled | LaunchRejected | AssemblyOrderRejected:
        open_orders = self.assembly_store.list_open_for_machine(machine_code)
        if not open_orders:
            return AssemblyOrderRejected("empty_session")
        session_need = _sum_lines(open_orders)
        gate = self._gate_session(session_need=session_need, machine_code=machine_code)
        if gate is not None:
            return gate

        cycle = self.cycle_store.load(machine_code)
        if cycle is None:
            cycle = MicromarketLoadingCycle(machine_code=machine_code)
        draft_lines = tuple(
            DraftLine(
                product_code=code,
                target_qty=0,
                stock_qty=Decimal("0"),
                need_qty=qty,
                launch_qty=qty,
            )
            for code, qty in sorted(session_need.items())
        )
        cycle.save_draft(draft_lines)
        self.cycle_store.save(cycle)

        result = self.launch.execute(machine_code=machine_code)
        if result is not None:
            return result

        for order in open_orders:
            consumed = order.consume()
            if isinstance(consumed, MicromarketAssemblyOrder):
                self.assembly_store.save(consumed)
        _LOGGER.info(
            "micromarket_assembly_orders_consumed",
            extra={
                "machine_code": machine_code,
                "order_ids": [o.order_id for o in open_orders],
                "actor": actor,
            },
        )
        return None

    @beartype
    def _gate_session(
        self,
        *,
        session_need: Mapping[str, Decimal],
        machine_code: str,
    ) -> AssemblyOrderRejected | None:
        if self.warehouse_stock is None:
            return None
        snapshot = self.warehouse_stock.get()
        if snapshot is None:
            return AssemblyOrderRejected("warehouse_snapshot_missing")
        others = tuple(o for o in self.assembly_store.list_open() if o.machine_code != machine_code)
        offenders: list[str] = []
        for code, need in session_need.items():
            available = available_for_code(
                snapshot=snapshot,
                open_orders=others,
                catalog_code=code,
            )
            if need > available:
                offenders.append(code)
        if offenders:
            return AssemblyOrderRejected(
                "qty_above_available",
                targets=tuple(sorted(set(offenders))),
            )
        return None


@beartype
def _parse_lines(
    lines: Mapping[str, Decimal],
) -> tuple[MicromarketAssemblyOrderLine, ...] | AssemblyOrderRejected:
    if not lines:
        return AssemblyOrderRejected("lines_empty")
    parsed: list[MicromarketAssemblyOrderLine] = []
    try:
        for code, qty in lines.items():
            parsed.append(MicromarketAssemblyOrderLine(catalog_code=code, qty=qty))
    except ValueError as error:
        return AssemblyOrderRejected(str(error))
    return tuple(parsed)


@beartype
def _sum_lines(orders: tuple[MicromarketAssemblyOrder, ...]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for order in orders:
        for line in order.lines:
            totals[line.catalog_code] = totals.get(line.catalog_code, Decimal("0")) + line.qty
    return totals
