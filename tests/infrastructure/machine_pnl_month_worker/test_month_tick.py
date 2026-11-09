from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.application.machine_pnl.opex_breakdown import empty_opex_breakdown
from src.domain.ids import MachineId
from src.domain.models import VendingMachine
from src.infrastructure.machine_pnl.month_memory import InMemoryMonthPnlSnapshotStore
from src.infrastructure.machine_pnl_month_worker.cron_tick import run_machine_pnl_month_tick

_MACHINE = MachineId("101")
_SURVIVING = MachineId("102")


def _minimal_month(
    *,
    revenue: Decimal = Decimal("0.00"),
    machine_id: MachineId = _MACHINE,
    period_start: date = date(2026, 6, 1),
) -> MonthPnlSnapshot:
    return MonthPnlSnapshot(
        machine_id=machine_id,
        location_id=None,
        technician_id=None,
        period_start=period_start,
        period_end=date(2026, 6, 30),
        revenue=revenue,
        revenue_known_as_of=date(2026, 6, 30),
        cogs_expected=Decimal("0.00"),
        cogs_actual_fact=Decimal("0.00"),
        cogs_actual_estimate=Decimal("0.00"),
        allocated_shortage_fact=Decimal("0.00"),
        allocated_shortage_estimate=Decimal("0.00"),
        allocated_surplus_fact=Decimal("0.00"),
        allocated_surplus_estimate=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        opex_known_total=Decimal("0.00"),
        net_theory=Decimal("0.00"),
        machine_gap=Decimal("0.00"),
        net_machine=Decimal("0.00"),
        tech_gap=Decimal("0.00"),
        net_after_tech=Decimal("0.00"),
        coverage_days=0,
        days_in_month=30,
        coverage_pct=Decimal("0"),
        projection_basis="none",
        warnings=(),
        last_recomputed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


@dataclass(frozen=True, slots=True)
class _ComputeCall:
    machine_id: MachineId
    period_start: date
    today: date


class _RecordingCompute:
    def __init__(self) -> None:
        self.calls: list[_ComputeCall] = []

    def execute(
        self,
        *,
        machine_id: MachineId,
        period_start: date,
        today: date,
    ) -> MonthPnlSnapshot:
        self.calls.append(
            _ComputeCall(machine_id=machine_id, period_start=period_start, today=today),
        )
        return _minimal_month(machine_id=machine_id, period_start=period_start)


class _RecordingSheetWriter:
    def __init__(self) -> None:
        self.rows: list[MonthPnlSnapshot] = []

    def upsert_rows(self, snapshots: Sequence[MonthPnlSnapshot]) -> None:
        self.rows = list(snapshots)


class _FailingThenOkCompute:
    def __init__(self) -> None:
        self.calls: list[_ComputeCall] = []

    def execute(
        self,
        *,
        machine_id: MachineId,
        period_start: date,
        today: date,
    ) -> MonthPnlSnapshot:
        self.calls.append(
            _ComputeCall(machine_id=machine_id, period_start=period_start, today=today),
        )
        if machine_id.value == _MACHINE.value:
            raise RuntimeError("stage1 failed")
        return _minimal_month(machine_id=machine_id, period_start=period_start)


def test_tick_recomputes_immature_months_and_exports_sheets() -> None:
    compute = _RecordingCompute()
    writer = _RecordingSheetWriter()
    coffee = VendingMachine(id=_MACHINE, name="A")
    run_machine_pnl_month_tick(
        machines=(coffee,),
        compute=compute,
        sheet_writer=writer,
        today=date(2026, 6, 15),
        tz=ZoneInfo("UTC"),
    )
    starts = {call.period_start for call in compute.calls}
    assert date(2026, 6, 1) in starts
    assert date(2026, 5, 1) in starts
    assert writer.rows  # upsert_rows called


def test_tick_skips_snack_machines() -> None:
    compute = _RecordingCompute()
    snack = VendingMachine(id=MachineId("501"), name="Snack")
    run_machine_pnl_month_tick(
        machines=(snack,),
        compute=compute,
        sheet_writer=_RecordingSheetWriter(),
        today=date(2026, 6, 15),
        tz=ZoneInfo("UTC"),
    )
    assert compute.calls == []


def test_tick_continues_when_one_machine_fails() -> None:
    compute = _FailingThenOkCompute()
    writer = _RecordingSheetWriter()
    failing = VendingMachine(id=_MACHINE, name="A")
    surviving = VendingMachine(id=_SURVIVING, name="B")
    run_machine_pnl_month_tick(
        machines=(failing, surviving),
        compute=compute,
        sheet_writer=writer,
        today=date(2026, 6, 15),
        tz=ZoneInfo("UTC"),
    )
    exported_ids = {snapshot.machine_id for snapshot in writer.rows}
    assert _SURVIVING in exported_ids
    assert _MACHINE not in exported_ids


def test_tick_exports_store_snapshots_not_only_computed_this_loop() -> None:
    compute = _RecordingCompute()
    writer = _RecordingSheetWriter()
    store = InMemoryMonthPnlSnapshotStore()
    extra = MachineId("199")
    store.upsert(
        _minimal_month(
            machine_id=extra,
            period_start=date(2026, 6, 1),
        )
    )
    store.upsert(
        _minimal_month(
            machine_id=extra,
            period_start=date(2026, 5, 1),
        )
    )
    coffee = VendingMachine(id=_MACHINE, name="A")
    run_machine_pnl_month_tick(
        machines=(coffee,),
        compute=compute,
        sheet_writer=writer,
        today=date(2026, 6, 15),
        tz=ZoneInfo("UTC"),
        month_store=store,
    )
    exported_ids = {snapshot.machine_id for snapshot in writer.rows}
    assert _MACHINE in exported_ids
    assert extra in exported_ids
    assert extra not in {call.machine_id for call in compute.calls}
