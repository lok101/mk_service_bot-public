from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from tests.application.close_period_helpers import build_close_period_deps
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.inventory_reconciliation import RefreshPendingPeriodReconciliations
from src.application.inventory_reconciliation.import_sales import (
    ImportKitVendingSales,
    ImportKitVendingSalesResult,
)
from src.application.inventory_reconciliation.kitvending import KitVendingFetchStats
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale
from src.infrastructure.alerting.sale_resolve_hold_notifier import (
    NoOpSaleResolveHoldAlertNotifier,
)
from src.infrastructure.composition.refresh_pending_with_accountability import (
    RefreshPendingWithAccountability,
)
from src.infrastructure.integrations.kitvending.api_models.enums import ResultCode
from src.infrastructure.integrations.kitvending.http_client import (
    KitVendingNetworkError,
    KitVendingResponseError,
)
from src.infrastructure.sales_ingest_worker import RefreshPendingExecutor, SalesIngestWorker
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)


@dataclass(slots=True)
class RecordingHoldNotifier:
    calls: list[dict[str, object]] = field(default_factory=list)

    def notify_holding(
        self,
        *,
        hold_at: datetime,
        holding_skip_count: int,
        fingerprint_pairs: object,
        samples: object,
    ) -> None:
        self.calls.append(
            {
                "hold_at": hold_at,
                "holding_skip_count": holding_skip_count,
                "fingerprint_pairs": fingerprint_pairs,
                "samples": samples,
            },
        )


@dataclass(slots=True)
class RecordingRefreshPending:
    called_with_machine_ids: list[MachineId] = field(default_factory=list)

    def execute(self, *, machine_id: MachineId | None = None) -> int:
        if machine_id is not None:
            self.called_with_machine_ids.append(machine_id)
        return 0


@dataclass(slots=True)
class HoldingImport:
    results: list[ImportKitVendingSalesResult]
    calls: int = 0

    def execute(self, *, since: datetime) -> ImportKitVendingSalesResult:
        del since
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result


@dataclass(slots=True)
class CapturingImport:
    result: ImportKitVendingSalesResult
    captured_since: list[datetime] = field(default_factory=list)

    def execute(self, *, since: datetime) -> ImportKitVendingSalesResult:
        self.captured_since.append(since)
        return self.result


@dataclass(slots=True)
class FlakyNetworkImport:
    poll_count: int = 0
    success_result: ImportKitVendingSalesResult = field(
        default_factory=lambda: ImportKitVendingSalesResult(
            inserted=0,
            skipped_unmapped=0,
            skipped_unresolved_product=0,
            skipped_no_machine_code=0,
            affected_machine_ids=(),
            batch_max_occurred_at=None,
        ),
    )

    def execute(self, *, since: datetime) -> ImportKitVendingSalesResult:
        self.poll_count += 1
        if self.poll_count == 1:
            raise KitVendingNetworkError("Ошибка сети: ConnectTimeout")
        return self.success_result


@dataclass(slots=True)
class ApiErrorImport:
    poll_count: int = 0
    result_code: int = int(ResultCode.INVALID_REQUEST_ID)

    def execute(self, *, since: datetime) -> ImportKitVendingSalesResult:
        self.poll_count += 1
        raise KitVendingResponseError("api error", result_code=self.result_code)


@dataclass(slots=True)
class SlowImportKitVendingSales:
    import_sales: ImportKitVendingSales
    gate: threading.Event
    poll_count: int = 0

    def execute(self, *, since: datetime) -> ImportKitVendingSalesResult:
        self.poll_count += 1
        self.gate.wait(timeout=5.0)
        return self.import_sales.execute(since=since)


_KV_ROW_VM01 = {
    "source_id": "kv-1",
    "vending_machine_code": "129",
    "product_code": "coffee-1",
    "quantity": "1",
    "occurred_at": "2026-06-05T12:00:00Z",
}

_KV_ROW_VM02 = {
    "source_id": "kv-2",
    "vending_machine_code": "501",
    "product_code": "coffee-2",
    "quantity": "1",
    "occurred_at": "2026-06-06T14:00:00Z",
}


def _worker(
    *,
    store: InMemoryMachineSalesStore,
    client: StubKitVendingClient,
    refresh: RefreshPendingExecutor,
    fixed_now: datetime | None = None,
    reconciliation_repo: InMemoryPeriodReconciliationRepository | None = None,
    tolerance_seconds: int = 0,
) -> SalesIngestWorker:
    now = fixed_now or datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
    return SalesIngestWorker(
        import_sales=ImportKitVendingSales(sales_store=store, kitvending_client=client),
        refresh_pending=refresh,
        sales_store=store,
        poll_interval_seconds=60.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=reconciliation_repo or InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=tolerance_seconds,
        now=lambda: now,
    )


def test_poll_once_calls_import_and_refresh() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(rows=[_KV_ROW_VM01, _KV_ROW_VM02])
    refresh = RecordingRefreshPending()
    worker = _worker(store=store, client=client, refresh=refresh)

    asyncio.run(worker.poll_once())

    assert store.load_global_cursor() == datetime(2026, 6, 6, 14, 0, tzinfo=UTC)
    assert store.max_occurred_at() == datetime(2026, 6, 6, 14, 0, tzinfo=UTC)
    assert refresh.called_with_machine_ids == [
        MachineId("129"),
        MachineId("501"),
    ]


def test_poll_once_uses_initial_lookback_when_store_empty() -> None:
    store = InMemoryMachineSalesStore()
    fixed_now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    client = StubKitVendingClient(rows=[_KV_ROW_VM01])
    refresh = RecordingRefreshPending()
    worker = _worker(
        store=store,
        client=client,
        refresh=refresh,
        fixed_now=fixed_now,
    )

    asyncio.run(worker.poll_once())

    assert store.load_global_cursor() == datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    assert store.max_occurred_at() == datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def test_poll_once_advances_cursor_for_unmapped_batch_without_inserts() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-unmapped",
                "vending_machine_code": "UNKNOWN",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-07T18:00:00Z",
            },
        ],
    )
    refresh = RecordingRefreshPending()
    fixed_now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    worker = SalesIngestWorker(
        import_sales=ImportKitVendingSales(
            sales_store=store,
            kitvending_client=client,
            code_resolver=MappingVendingMachineCodeResolver({}),
        ),
        refresh_pending=refresh,
        sales_store=store,
        poll_interval_seconds=60.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        now=lambda: fixed_now,
    )

    asyncio.run(worker.poll_once())

    assert store.max_occurred_at() is None
    assert store.load_global_cursor() == datetime(2026, 6, 7, 18, 0, tzinfo=UTC)
    assert refresh.called_with_machine_ids == []


def test_run_loads_persisted_cursor_at_start() -> None:
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(datetime(2026, 6, 6, 10, 0, tzinfo=UTC))
    client = StubKitVendingClient(rows=[])
    refresh = RecordingRefreshPending()
    worker = _worker(store=store, client=client, refresh=refresh)
    stop = asyncio.Event()
    stop.set()

    asyncio.run(worker.run(stop))

    assert worker._poll_cursor == datetime(2026, 6, 6, 10, 0, tzinfo=UTC)


def test_poll_once_skips_when_busy() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(rows=[_KV_ROW_VM01])
    refresh = RecordingRefreshPending()
    gate = threading.Event()
    slow_import = SlowImportKitVendingSales(
        import_sales=ImportKitVendingSales(sales_store=store, kitvending_client=client),
        gate=gate,
    )
    worker = SalesIngestWorker(
        import_sales=slow_import,
        refresh_pending=refresh,
        sales_store=store,
        poll_interval_seconds=60.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
    )

    async def _run_overlap() -> None:
        first = asyncio.create_task(worker.poll_once())
        await asyncio.sleep(0.05)
        await worker.poll_once()
        gate.set()
        await first

    asyncio.run(_run_overlap())

    assert slow_import.poll_count == 1


def test_run_stops_when_event_set() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(rows=[_KV_ROW_VM01])
    refresh = RecordingRefreshPending()
    fixed_now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    worker = SalesIngestWorker(
        import_sales=ImportKitVendingSales(sales_store=store, kitvending_client=client),
        refresh_pending=refresh,
        sales_store=store,
        poll_interval_seconds=0.05,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        now=lambda: fixed_now,
    )
    stop = asyncio.Event()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        stop.set()

    async def _run() -> None:
        stopper = asyncio.create_task(_stop_soon())
        await worker.run(stop)
        await stopper

    start = time.monotonic()
    asyncio.run(_run())
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert store.max_occurred_at() is not None


def test_refresh_pending_accepts_real_type() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(rows=[_KV_ROW_VM01])
    repo = InMemoryPeriodReconciliationRepository()
    form_store, history, _, _ = build_close_period_deps()
    settlement_repo = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    refresh = RefreshPendingWithAccountability(
        refresh=RefreshPendingPeriodReconciliations(
            repo=repo,
            sales_store=store,
            coffee_recipe_repo=InMemoryCoffeeRecipeRepository(),
            domain_product_store=FakeDomainProductStore(),
            form_submission_store=form_store,
            revision_history=history,
            tolerance_seconds=300,
        ),
        post_accountability=PostPeriodAccountability(
            settlement_executor=TechnicianSettlementExecutor(repository=settlement_repo),
            reconciliation_repo=repo,
        ),
    )
    worker = _worker(store=store, client=client, refresh=refresh)

    asyncio.run(worker.poll_once())

    assert store.max_occurred_at() is not None


def test_run_survives_network_error_and_polls_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(datetime(2026, 6, 4, 10, 0, tzinfo=UTC))
    flaky = FlakyNetworkImport()
    refresh = RecordingRefreshPending()
    worker = SalesIngestWorker(
        import_sales=flaky,
        refresh_pending=refresh,
        sales_store=store,
        poll_interval_seconds=0.02,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
    )
    stop = asyncio.Event()

    async def _stop_after_two_polls() -> None:
        while flaky.poll_count < 2:
            await asyncio.sleep(0.01)
        stop.set()

    async def _run() -> None:
        await asyncio.gather(worker.run(stop), _stop_after_two_polls())

    asyncio.run(_run())

    assert flaky.poll_count == 2
    assert store.load_global_cursor() == datetime(2026, 6, 4, 10, 0, tzinfo=UTC)
    network_records = [
        record
        for record in caplog.records
        if record.getMessage() == "kitvending_import_network_error"
    ]
    assert len(network_records) == 1
    assert network_records[0].exception_type == "KitVendingNetworkError"


def test_poll_once_survives_recoverable_api_error_14() -> None:
    cursor = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(cursor)
    import_sales = ApiErrorImport(result_code=int(ResultCode.INVALID_REQUEST_ID))
    worker = SalesIngestWorker(
        import_sales=import_sales,
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=60.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
    )

    asyncio.run(worker.poll_once())

    assert import_sales.poll_count == 1
    assert store.load_global_cursor() == cursor


def test_poll_once_survives_recoverable_api_error_27() -> None:
    store = InMemoryMachineSalesStore()
    import_sales = ApiErrorImport(result_code=int(ResultCode.TOO_MANY_REQUEST))
    worker = SalesIngestWorker(
        import_sales=import_sales,
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=60.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
    )

    asyncio.run(worker.poll_once())

    assert import_sales.poll_count == 1
    assert store.load_global_cursor() is None


def test_poll_once_propagates_non_recoverable_api_error() -> None:
    store = InMemoryMachineSalesStore()
    import_sales = ApiErrorImport(result_code=5)
    worker = SalesIngestWorker(
        import_sales=import_sales,
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=60.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
    )

    with pytest.raises(KitVendingResponseError, match="api error"):
        asyncio.run(worker.poll_once())


def test_run_survives_recoverable_api_error_and_polls_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    store = InMemoryMachineSalesStore()
    import_sales = ApiErrorImport(result_code=int(ResultCode.INVALID_REQUEST_ID))
    worker = SalesIngestWorker(
        import_sales=import_sales,
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=0.01,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
    )
    stop = asyncio.Event()

    async def _stop_after_two_polls() -> None:
        while import_sales.poll_count < 2:
            await asyncio.sleep(0.01)
        stop.set()

    async def _run() -> None:
        await asyncio.gather(worker.run(stop), _stop_after_two_polls())

    asyncio.run(_run())

    assert import_sales.poll_count == 2
    assert any(record.getMessage() == "kitvending_import_api_error" for record in caplog.records)


def test_poll_once_logs_fetch_skip_stats(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[_KV_ROW_VM01],
        fetch_stats=KitVendingFetchStats(
            skipped_unresolved_product=2,
            skipped_no_machine_code=1,
        ),
    )
    refresh = RecordingRefreshPending()
    worker = _worker(store=store, client=client, refresh=refresh)

    asyncio.run(worker.poll_once())

    stats_records = [
        record
        for record in caplog.records
        if getattr(record, "skipped_unresolved_product", None) is not None
    ]
    assert len(stats_records) == 1
    assert stats_records[0].skipped_unresolved_product == 2
    assert stats_records[0].skipped_no_machine_code == 1


def test_poll_once_clamps_cursor_on_holding() -> None:
    store = InMemoryMachineSalesStore()
    hold = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    earlier = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    later = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
    previous = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
    store.save_global_cursor(previous)
    worker = SalesIngestWorker(
        import_sales=HoldingImport(
            [
                ImportKitVendingSalesResult(
                    inserted=2,
                    skipped_unmapped=0,
                    affected_machine_ids=(),
                    success_occurred_ats=(earlier, later),
                    batch_max_occurred_at=later,
                    hold_at=hold,
                    holding_skip_count=1,
                    fingerprint_pairs=(("176", "critical_product_resolve"),),
                )
            ]
        ),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        resolve_hold_notifier=NoOpSaleResolveHoldAlertNotifier(),
    )
    worker._poll_cursor = previous
    asyncio.run(worker.poll_once())
    assert store.load_global_cursor() == earlier


def test_poll_once_does_not_clamp_on_non_holding_skips() -> None:
    store = InMemoryMachineSalesStore()
    batch_max = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    worker = SalesIngestWorker(
        import_sales=HoldingImport(
            [
                ImportKitVendingSalesResult(
                    inserted=1,
                    skipped_unmapped=0,
                    affected_machine_ids=(),
                    skipped_unresolved_product=3,
                    success_occurred_ats=(batch_max,),
                    batch_max_occurred_at=batch_max,
                    hold_at=None,
                    holding_skip_count=0,
                )
            ]
        ),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        resolve_hold_notifier=NoOpSaleResolveHoldAlertNotifier(),
    )
    asyncio.run(worker.poll_once())
    assert store.load_global_cursor() == batch_max


def test_poll_once_clamps_without_alert_config() -> None:
    store = InMemoryMachineSalesStore()
    hold = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    earlier = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    previous = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
    store.save_global_cursor(previous)
    worker = SalesIngestWorker(
        import_sales=HoldingImport(
            [
                ImportKitVendingSalesResult(
                    inserted=1,
                    skipped_unmapped=0,
                    affected_machine_ids=(),
                    success_occurred_ats=(earlier,),
                    batch_max_occurred_at=earlier,
                    hold_at=hold,
                    holding_skip_count=1,
                    fingerprint_pairs=(("176", "critical_product_resolve"),),
                )
            ]
        ),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        resolve_hold_notifier=NoOpSaleResolveHoldAlertNotifier(),
    )
    worker._poll_cursor = previous
    asyncio.run(worker.poll_once())
    assert store.load_global_cursor() == earlier


def test_poll_once_hold_then_success_advances_cursor() -> None:
    store = InMemoryMachineSalesStore()
    hold = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    earlier = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    later = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    previous = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
    store.save_global_cursor(previous)
    worker = SalesIngestWorker(
        import_sales=HoldingImport(
            [
                ImportKitVendingSalesResult(
                    inserted=1,
                    skipped_unmapped=0,
                    affected_machine_ids=(),
                    success_occurred_ats=(earlier,),
                    batch_max_occurred_at=earlier,
                    hold_at=hold,
                    holding_skip_count=1,
                    fingerprint_pairs=(("176", "critical_product_resolve"),),
                ),
                ImportKitVendingSalesResult(
                    inserted=1,
                    skipped_unmapped=0,
                    affected_machine_ids=(),
                    success_occurred_ats=(later,),
                    batch_max_occurred_at=later,
                    hold_at=None,
                    holding_skip_count=0,
                ),
            ]
        ),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        resolve_hold_notifier=NoOpSaleResolveHoldAlertNotifier(),
    )
    worker._poll_cursor = previous
    asyncio.run(worker.poll_once())
    assert store.load_global_cursor() == earlier
    asyncio.run(worker.poll_once())
    assert store.load_global_cursor() == later


def test_poll_once_refreshes_pending_covered_by_cursor_without_affected() -> None:
    # happy: cursor already ahead, empty import batch, pending on other machine
    store = InMemoryMachineSalesStore()
    closed = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
    store.save_global_cursor(closed)
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(
        ResponsibilityPeriodReconciliation(
            period_id="rev-a:rev-b",
            machine_id=MachineId("vm-pending"),
            responsible_technician_id=TechnicianId("tech-a"),
            opening_revision_id=RevisionId("rev-a"),
            closing_revision_id=RevisionId("rev-b"),
            opened_at=datetime(2026, 6, 1, tzinfo=UTC),
            closed_at=closed,
            lines=(),
            sales_lines=(),
            load_count=0,
            status="pending_sales",
        ),
    )
    refresh = RecordingRefreshPending()
    client = StubKitVendingClient(rows=[])  # successful empty import
    worker = SalesIngestWorker(
        import_sales=ImportKitVendingSales(sales_store=store, kitvending_client=client),
        refresh_pending=refresh,
        sales_store=store,
        poll_interval_seconds=60.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=repo,
        tolerance_seconds=0,
        now=lambda: datetime(2026, 6, 10, tzinfo=UTC),
    )
    asyncio.run(worker.poll_once())
    assert MachineId("vm-pending") in refresh.called_with_machine_ids


def test_poll_once_skips_cursor_refresh_on_kitvending_network_error() -> None:
    # error: network abort — no refresh
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(datetime(2026, 6, 8, 10, 0, tzinfo=UTC))
    refresh = RecordingRefreshPending()
    worker = SalesIngestWorker(
        import_sales=FlakyNetworkImport(),  # first poll raises KitVendingNetworkError
        refresh_pending=refresh,
        sales_store=store,
        poll_interval_seconds=60.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        now=lambda: datetime(2026, 6, 10, tzinfo=UTC),
    )
    asyncio.run(worker.poll_once())
    assert refresh.called_with_machine_ids == []


def test_poll_once_uses_overlap_for_fetch_since() -> None:
    store = InMemoryMachineSalesStore()
    true_cursor = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    store.save_global_cursor(true_cursor)
    import_sales = CapturingImport(
        result=ImportKitVendingSalesResult(
            inserted=0,
            skipped_unmapped=0,
            affected_machine_ids=(),
        ),
    )
    worker = SalesIngestWorker(
        import_sales=import_sales,
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        overlap_seconds=600,
    )
    worker._poll_cursor = true_cursor

    asyncio.run(worker.poll_once())

    assert import_sales.captured_since == [true_cursor - timedelta(seconds=600)]


def test_poll_once_overlap_defaults_to_zero_matches_true_cursor() -> None:
    store = InMemoryMachineSalesStore()
    true_cursor = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    store.save_global_cursor(true_cursor)
    import_sales = CapturingImport(
        result=ImportKitVendingSalesResult(
            inserted=0,
            skipped_unmapped=0,
            affected_machine_ids=(),
        ),
    )
    worker = SalesIngestWorker(
        import_sales=import_sales,
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
    )  # overlap_seconds not passed -> default 0, byte-for-byte old behavior
    worker._poll_cursor = true_cursor

    asyncio.run(worker.poll_once())

    assert import_sales.captured_since == [true_cursor]


def test_poll_once_overlap_duplicates_do_not_roll_back_cursor() -> None:
    store = InMemoryMachineSalesStore()
    true_cursor = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    duplicate_occurred_at = datetime(2026, 8, 12, 9, 45, tzinfo=UTC)
    store.save_global_cursor(true_cursor)
    import_sales = HoldingImport(
        [
            ImportKitVendingSalesResult(
                inserted=0,
                skipped_unmapped=0,
                affected_machine_ids=(),
                success_occurred_ats=(duplicate_occurred_at,),
                inserted_occurred_ats=(),
                hold_at=None,
            ),
        ],
    )
    worker = SalesIngestWorker(
        import_sales=import_sales,
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        overlap_seconds=1800,
    )
    worker._poll_cursor = true_cursor

    asyncio.run(worker.poll_once())

    assert store.load_global_cursor() == true_cursor


def test_poll_once_holding_unaffected_by_overlap() -> None:
    store = InMemoryMachineSalesStore()
    hold = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    earlier = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    later = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
    previous = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
    store.save_global_cursor(previous)
    worker = SalesIngestWorker(
        import_sales=HoldingImport(
            [
                ImportKitVendingSalesResult(
                    inserted=2,
                    skipped_unmapped=0,
                    affected_machine_ids=(),
                    success_occurred_ats=(earlier, later),
                    batch_max_occurred_at=later,
                    hold_at=hold,
                    holding_skip_count=1,
                    fingerprint_pairs=(("176", "critical_product_resolve"),),
                ),
            ],
        ),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        overlap_seconds=1800,
        resolve_hold_notifier=NoOpSaleResolveHoldAlertNotifier(),
    )
    worker._poll_cursor = previous

    asyncio.run(worker.poll_once())

    assert store.load_global_cursor() == earlier


def test_poll_once_skips_holding_notify_when_hold_at_before_true_cursor() -> None:
    store = InMemoryMachineSalesStore()
    true_cursor = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    hold_at = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    store.save_global_cursor(true_cursor)
    notifier = RecordingHoldNotifier()
    worker = SalesIngestWorker(
        import_sales=HoldingImport(
            [
                ImportKitVendingSalesResult(
                    inserted=0,
                    skipped_unmapped=0,
                    affected_machine_ids=(),
                    success_occurred_ats=(hold_at,),
                    batch_max_occurred_at=hold_at,
                    hold_at=hold_at,
                    holding_skip_count=1,
                    fingerprint_pairs=(("176", "critical_product_resolve"),),
                ),
            ],
        ),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        overlap_seconds=1800,
        resolve_hold_notifier=notifier,
    )
    worker._poll_cursor = true_cursor

    asyncio.run(worker.poll_once())

    assert notifier.calls == []


def test_poll_once_notifies_holding_when_hold_at_at_or_after_true_cursor() -> None:
    store = InMemoryMachineSalesStore()
    true_cursor = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    hold_at = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    earlier = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    store.save_global_cursor(true_cursor)
    notifier = RecordingHoldNotifier()
    worker = SalesIngestWorker(
        import_sales=HoldingImport(
            [
                ImportKitVendingSalesResult(
                    inserted=1,
                    skipped_unmapped=0,
                    affected_machine_ids=(),
                    success_occurred_ats=(earlier,),
                    batch_max_occurred_at=earlier,
                    hold_at=hold_at,
                    holding_skip_count=2,
                    fingerprint_pairs=(("176", "critical_product_resolve"),),
                ),
            ],
        ),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        resolve_hold_notifier=notifier,
    )
    worker._poll_cursor = true_cursor

    asyncio.run(worker.poll_once())

    assert len(notifier.calls) == 1
    assert notifier.calls[0]["hold_at"] == hold_at
    assert notifier.calls[0]["holding_skip_count"] == 2


def test_poll_once_overlap_recovers_late_arrival_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    store = InMemoryMachineSalesStore()
    true_cursor = datetime(2026, 6, 10, 10, 0, tzinfo=UTC)
    store.save_global_cursor(true_cursor)
    late_row = {
        "source_id": "kv-late",
        "vending_machine_code": "129",
        "product_code": "coffee-1",
        "quantity": "1",
        "occurred_at": "2026-06-10T09:45:00Z",
    }
    client = StubKitVendingClient(rows=[late_row])
    worker = SalesIngestWorker(
        import_sales=ImportKitVendingSales(sales_store=store, kitvending_client=client),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        overlap_seconds=1800,
    )
    worker._poll_cursor = true_cursor

    asyncio.run(worker.poll_once())

    assert store.max_occurred_at() == datetime(2026, 6, 10, 9, 45, tzinfo=UTC)
    late_records = [
        record
        for record in caplog.records
        if record.getMessage() == "kitvending_late_arrival_recovered"
    ]
    assert len(late_records) == 1
    assert late_records[0].count == 1
    assert late_records[0].min_occurred_at == "2026-06-10T09:45:00+00:00"
    assert late_records[0].true_cursor == true_cursor.isoformat()


def test_poll_once_no_log_for_duplicate_within_overlap(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    store = InMemoryMachineSalesStore()
    true_cursor = datetime(2026, 6, 10, 10, 0, tzinfo=UTC)
    duplicate_occurred_at = datetime(2026, 6, 10, 9, 45, tzinfo=UTC)
    store.save_global_cursor(true_cursor)
    store.insert_if_absent(
        MachineSale(
            source_id="kv-dup",
            machine_id=MachineId("129"),
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=duplicate_occurred_at,
            ingested_at=duplicate_occurred_at,
        ),
    )
    duplicate_row = {
        "source_id": "kv-dup",
        "vending_machine_code": "129",
        "product_code": "coffee-1",
        "quantity": "1",
        "occurred_at": "2026-06-10T09:45:00Z",
    }
    client = StubKitVendingClient(rows=[duplicate_row])
    worker = SalesIngestWorker(
        import_sales=ImportKitVendingSales(sales_store=store, kitvending_client=client),
        refresh_pending=RecordingRefreshPending(),
        sales_store=store,
        poll_interval_seconds=900.0,
        initial_lookback=timedelta(days=7),
        reconciliation_repo=InMemoryPeriodReconciliationRepository(),
        tolerance_seconds=0,
        overlap_seconds=1800,
    )
    worker._poll_cursor = true_cursor

    asyncio.run(worker.poll_once())

    late_records = [
        record
        for record in caplog.records
        if record.getMessage() == "kitvending_late_arrival_recovered"
    ]
    assert late_records == []
    assert store.load_global_cursor() == true_cursor
