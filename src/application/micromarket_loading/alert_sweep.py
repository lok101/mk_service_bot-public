from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.calendar import operational_day
from src.domain.micromarket_loading.order import MicromarketLoadingCycle, OrderStatus

_LOGGER = logging.getLogger(__name__)

# Open/recounted chat alerts off: штатный незакрытый ордер — не инцидент, шум в
# TELEGRAM_ALERT_CHAT_ID. Sweep/worker оставлены; просрочки обслуживания и
# warehouse-stock staleness идут другими путями.
_ALERTABLE: frozenset[OrderStatus] = frozenset()


@runtime_checkable
class MicromarketLoadingAlertCycleStore(Protocol):
    def list_cycles(self) -> tuple[MicromarketLoadingCycle, ...]: ...

    def save(self, cycle: MicromarketLoadingCycle) -> None: ...


@runtime_checkable
class MicromarketLoadingAlerter(Protocol):
    def send(self, text: str) -> None: ...


@runtime_checkable
class MicromarketLoadingMachineNameLookup(Protocol):
    def display_name(self, machine_code: str) -> str: ...


@beartype
@dataclass(slots=True)
class SweepMicromarketLoadingAlerts:
    cycle_store: MicromarketLoadingAlertCycleStore
    alerter: MicromarketLoadingAlerter
    names: MicromarketLoadingMachineNameLookup
    timezone: ZoneInfo
    day_end_hour: int

    @beartype
    def sweep_once(self, now: datetime) -> None:
        day = operational_day(now, self.timezone, self.day_end_hour)
        for cycle in self.cycle_store.list_cycles():
            self._sweep_cycle(cycle, day=day)

    @beartype
    def _sweep_cycle(self, cycle: MicromarketLoadingCycle, *, day: date) -> None:
        if cycle.status not in _ALERTABLE:
            return
        order_id = cycle.order_id
        if order_id is None:
            return
        if cycle.was_alerted(order_id=order_id, operational_day=day):
            return
        status_value = cycle.status.value if cycle.status is not None else ""
        name = self.names.display_name(cycle.machine_code)
        text = (
            f"micromarket loading order open: machine={cycle.machine_code} "
            f"name={name} order_id={order_id} status={status_value}"
        )
        self.alerter.send(text)
        cycle.record_alert(order_id=order_id, operational_day=day)
        self.cycle_store.save(cycle)
        _LOGGER.info(
            "micromarket_loading_alert_sent",
            extra={"machine_code": cycle.machine_code, "order_id": order_id},
        )
