from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.domain.ids import MachineId
from src.domain.machine_sales_classify import is_snack_machine_code
from src.domain.models import VendingMachine

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class MonthPnlMonthTickCompute(Protocol):
    def execute(
        self,
        *,
        machine_id: MachineId,
        period_start: date,
        today: date,
    ) -> MonthPnlSnapshot: ...


@runtime_checkable
class MonthPnlMonthTickSheetWriter(Protocol):
    def upsert_rows(self, snapshots: Sequence[MonthPnlSnapshot]) -> None: ...


@runtime_checkable
class MonthPnlMonthTickSnapshotStore(Protocol):
    def list_for_period_starts(
        self,
        period_starts: Sequence[date],
    ) -> Sequence[MonthPnlSnapshot]: ...


def _catch_up_period_starts(today: date) -> tuple[date, date]:
    current = date(today.year, today.month, 1)
    if today.month == 1:
        previous = date(today.year - 1, 12, 1)
    else:
        previous = date(today.year, today.month - 1, 1)
    return current, previous


@beartype
def run_machine_pnl_month_tick(
    *,
    machines: Sequence[VendingMachine],
    compute: MonthPnlMonthTickCompute,
    sheet_writer: MonthPnlMonthTickSheetWriter,
    today: date,
    tz: ZoneInfo,
    month_store: MonthPnlMonthTickSnapshotStore | None = None,
) -> None:
    del tz
    period_starts = _catch_up_period_starts(today)
    snapshots: list[MonthPnlSnapshot] = []
    for machine in machines:
        if is_snack_machine_code(machine.id.value):
            continue
        for period_start in period_starts:
            try:
                snapshot = compute.execute(
                    machine_id=machine.id,
                    period_start=period_start,
                    today=today,
                )
            except Exception:
                _LOGGER.exception(
                    "machine_pnl_month_tick_failed machine_id=%s period_start=%s",
                    machine.id.value,
                    period_start,
                )
                continue
            snapshots.append(snapshot)
    exported_by_key: dict[tuple[str, date], MonthPnlSnapshot] = {}
    if month_store is not None:
        for stored in month_store.list_for_period_starts(period_starts):
            exported_by_key[(stored.machine_id.value, stored.period_start)] = stored
    for snapshot in snapshots:
        exported_by_key[(snapshot.machine_id.value, snapshot.period_start)] = snapshot
    exported = tuple(exported_by_key.values())
    _LOGGER.info(
        "machine_pnl_month_tick computed=%s exported=%s periods=%s",
        len(snapshots),
        len(exported),
        ",".join(period.isoformat() for period in period_starts),
    )
    sheet_writer.upsert_rows(exported)
