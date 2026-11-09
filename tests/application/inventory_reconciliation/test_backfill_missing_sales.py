from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.application.inventory_reconciliation.backfill_missing_sales import (
    BackfillMissingSalesFromKit,
)
from src.application.inventory_reconciliation.import_sales import ImportKitVendingSalesResult
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
)

_SINCE = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
_UNTIL = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)


@dataclass(slots=True)
class _FakeImportSales:
    result: ImportKitVendingSalesResult
    captured: list[tuple[datetime, datetime | None]] = field(default_factory=list)

    def execute(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> ImportKitVendingSalesResult:
        self.captured.append((since, until))
        return self.result


@dataclass(slots=True)
class _RecordingRefreshPending:
    called_with: list[MachineId] = field(default_factory=list)

    def execute(self, *, machine_id: MachineId | None = None) -> object:
        if machine_id is not None:
            self.called_with.append(machine_id)
        return None


@dataclass(slots=True)
class _RecordingCursorStore(InMemoryMachineSalesStore):
    save_calls: list[datetime] = field(default_factory=list)

    def save_global_cursor(self, watermark: datetime) -> None:
        self.save_calls.append(watermark)
        return super().save_global_cursor(watermark)


def _pending_snapshot(machine_id: str, closed_at: datetime) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=f"rev-a:{machine_id}",
        machine_id=MachineId(machine_id),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-a"),
        closing_revision_id=RevisionId("rev-b"),
        opened_at=closed_at - timedelta(days=1),
        closed_at=closed_at,
        lines=(),
        sales_lines=(),
        load_count=0,
        status="pending_sales",
    )


def test_execute_skips_settlement_refresh_by_default() -> None:
    store = InMemoryMachineSalesStore()
    closed = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
    store.save_global_cursor(closed + timedelta(hours=1))
    preset_cursor = store.load_global_cursor()
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_pending_snapshot("vm-pending", closed))
    import_sales = _FakeImportSales(
        result=ImportKitVendingSalesResult(
            inserted=1,
            skipped_unmapped=0,
            affected_machine_ids=(MachineId("vm-01"),),
        ),
    )
    refresh_pending = _RecordingRefreshPending()
    use_case = BackfillMissingSalesFromKit(
        import_sales=import_sales,
        sales_store=store,
        reconciliation_repo=repo,
        refresh_pending=refresh_pending,
        tolerance_seconds=0,
    )

    result = use_case.execute(since=_SINCE, until=_UNTIL)

    assert refresh_pending.called_with == []
    assert result.refreshed_machine_count == 0
    assert result.inserted == 1
    assert store.load_global_cursor() == preset_cursor


def test_execute_refresh_settlement_true_refreshes_affected() -> None:
    store = InMemoryMachineSalesStore()
    import_sales = _FakeImportSales(
        result=ImportKitVendingSalesResult(
            inserted=1,
            skipped_unmapped=0,
            affected_machine_ids=(MachineId("vm-01"),),
        ),
    )
    refresh_pending = _RecordingRefreshPending()
    use_case = BackfillMissingSalesFromKit(
        import_sales=import_sales,
        sales_store=store,
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        refresh_pending=refresh_pending,
        tolerance_seconds=0,
    )

    result = use_case.execute(
        since=_SINCE,
        until=_UNTIL,
        refresh_settlement=True,
    )

    assert import_sales.captured == [(_SINCE, _UNTIL)]
    assert refresh_pending.called_with == [MachineId("vm-01")]
    assert result.inserted == 1
    assert result.refreshed_machine_count == 1
    assert result.window_from == _SINCE
    assert result.window_to == _UNTIL
    assert store.load_global_cursor() is None


def test_execute_also_refreshes_pending_due_by_cursor_even_without_affected() -> None:
    # edge: pending-due по существующему курсору подхватывается вместе с пустым affected
    store = InMemoryMachineSalesStore()
    closed = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
    store.save_global_cursor(closed + timedelta(hours=1))
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_pending_snapshot("vm-pending", closed))
    import_sales = _FakeImportSales(
        result=ImportKitVendingSalesResult(
            inserted=0,
            skipped_unmapped=0,
            affected_machine_ids=(),
        ),
    )
    refresh_pending = _RecordingRefreshPending()
    use_case = BackfillMissingSalesFromKit(
        import_sales=import_sales,
        sales_store=store,
        reconciliation_repo=repo,
        refresh_pending=refresh_pending,
        tolerance_seconds=0,
    )

    result = use_case.execute(since=_SINCE, until=_UNTIL, refresh_settlement=True)

    assert refresh_pending.called_with == [MachineId("vm-pending")]
    assert result.refreshed_machine_count == 1


def test_backfill_missing_sales_never_calls_save_global_cursor() -> None:
    # invariant: курсор только read (spy), даже при hold_at/holding и pre-set cursor
    store = _RecordingCursorStore()
    store.save_global_cursor(datetime(2026, 8, 1, tzinfo=UTC))  # pre-set
    store.save_calls.clear()
    import_sales = _FakeImportSales(
        result=ImportKitVendingSalesResult(
            inserted=0,
            skipped_unmapped=0,
            affected_machine_ids=(),
            hold_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            holding_skip_count=3,
        ),
    )
    use_case = BackfillMissingSalesFromKit(
        import_sales=import_sales,
        sales_store=store,
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        refresh_pending=_RecordingRefreshPending(),
        tolerance_seconds=0,
    )

    result = use_case.execute(since=_SINCE, until=_UNTIL, refresh_settlement=True)

    assert store.save_calls == []
    assert store.load_global_cursor() is not None  # pre-set сохранён
    assert result.holding_skip_count == 3


def test_execute_second_run_on_overlapping_window_is_idempotent() -> None:
    # idempotency: второй прогон на пересекающемся окне не удваивает refresh-эффект
    # для уже обработанной машины (тот же affected id, повторный refresh — no-op
    # по семантике refresh)
    store = InMemoryMachineSalesStore()
    import_sales = _FakeImportSales(
        result=ImportKitVendingSalesResult(
            inserted=0,  # уже вставлено первым прогоном
            skipped_unmapped=0,
            affected_machine_ids=(MachineId("vm-01"),),
        ),
    )
    refresh_pending = _RecordingRefreshPending()
    use_case = BackfillMissingSalesFromKit(
        import_sales=import_sales,
        sales_store=store,
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        refresh_pending=refresh_pending,
        tolerance_seconds=0,
    )

    use_case.execute(since=_SINCE, until=_UNTIL, refresh_settlement=True)
    result = use_case.execute(since=_SINCE, until=_UNTIL, refresh_settlement=True)

    assert result.inserted == 0
    assert refresh_pending.called_with == [MachineId("vm-01"), MachineId("vm-01")]
    assert store.load_global_cursor() is None
