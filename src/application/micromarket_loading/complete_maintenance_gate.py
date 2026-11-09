from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.master_data import MachineKind
from src.application.micromarket_loading.maintenance_gate import (
    has_micromarket_inventory_in_operational_day,
)
from src.application.micromarket_loading.ports import (
    MachineKindLookup,
    MicromarketDeviceStockStore,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.domain.ids import MachineId
from src.domain.micromarket_loading.order import OrderStatus

MICROMARKET_INVENTORY_REQUIRED_REASON = (
    "Нужна инвентаризация микромаркета за текущий operational day."
)

MICROMARKET_LOADING_PHOTOS_OPEN_REASON = "Сначала пересчёт микромаркета."

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketCompleteMaintenanceInventoryGate:
    kind_lookup: MachineKindLookup
    stock_store: MicromarketDeviceStockStore
    timezone: ZoneInfo
    day_end_hour: int
    order_store: MicromarketLoadingCycleStore | None = None

    @beartype
    def complete_maintenance_block_reason(
        self,
        machine_id: MachineId,
        checked_at: datetime,
    ) -> str | None:
        if not self._is_micromarket(machine_id):
            return None
        events = self.stock_store.list_events(machine_id.value)
        has_inventory = has_micromarket_inventory_in_operational_day(
            events,
            checked_at=checked_at,
            timezone=self.timezone,
            day_end_hour=self.day_end_hour,
        )
        open_block = self._open_order_block_reason(machine_id)
        if has_inventory:
            return open_block
        if open_block is not None:
            return MICROMARKET_INVENTORY_REQUIRED_REASON
        if self._order_is_closed(machine_id):
            return None
        return MICROMARKET_INVENTORY_REQUIRED_REASON

    @beartype
    def suppress_coffee_revision(self, machine_id: MachineId) -> bool:
        return self._is_micromarket(machine_id)

    @beartype
    def loading_photos_block_reason(
        self,
        machine_id: MachineId,
        checked_at: datetime,
    ) -> str | None:
        del checked_at
        return self._open_order_block_reason(machine_id)

    @beartype
    def close_loading_order_after_visit_final(self, machine_id: MachineId) -> None:
        if not self._is_micromarket(machine_id) or self.order_store is None:
            return
        cycle = self.order_store.load(machine_id.value)
        if cycle is None:
            return
        if cycle.status is OrderStatus.CLOSED:
            return
        if cycle.status is not OrderStatus.RECOUNTED:
            return
        cycle.close(at=datetime.now(UTC))
        self.order_store.save(cycle)
        _logger.info(
            "micromarket_loading_closed_after_visit_final",
            extra={"machine_code": machine_id.value, "order_id": cycle.order_id},
        )

    @beartype
    def _open_order_block_reason(self, machine_id: MachineId) -> str | None:
        if not self._is_micromarket(machine_id) or self.order_store is None:
            return None
        cycle = self.order_store.load(machine_id.value)
        if cycle is not None and cycle.status is OrderStatus.OPEN:
            return MICROMARKET_LOADING_PHOTOS_OPEN_REASON
        return None

    @beartype
    def _order_is_closed(self, machine_id: MachineId) -> bool:
        if self.order_store is None:
            return False
        cycle = self.order_store.load(machine_id.value)
        return cycle is not None and cycle.status is OrderStatus.CLOSED

    @beartype
    def _is_micromarket(self, machine_id: MachineId) -> bool:
        return self.kind_lookup.kind_of(machine_id.value) is MachineKind.MICRO_MARKET
