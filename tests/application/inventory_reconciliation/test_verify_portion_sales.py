from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.inventory_reconciliation.kitvending import (
    KitSaleResolveSkip,
    KitSaleResolveSuccess,
    KitVendingSaleRow,
    RawKitSaleIdentity,
)
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.application.inventory_reconciliation.sale_skip import MachineSaleSkip
from src.application.inventory_reconciliation.verify_portion_sales import (
    VerifyPortionSales,
    VerifyPortionSalesHoldingError,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.machine_sales_skipped_fakes import InMemoryMachineSaleSkipStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
)

_TECH = TechnicianId("t1")
_MACHINE = MachineId("vm-01")
_CUTOFF = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
_OPENED = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
_INGESTED = datetime(2026, 8, 5, 11, 0, tzinfo=UTC)
_SOURCE_A = "kit:10:2026-08-02T10:00:00:1:100"
_SOURCE_B = "kit:10:2026-08-03T10:00:00:2:100"
_CODE = "VM01"


def _period(
    *,
    period_id: str = "p1",
    machine_id: MachineId = _MACHINE,
    status: str = "complete",
    ledger_posted: bool = True,
    opened_at: datetime = _OPENED,
    closed_at: datetime = _CLOSED,
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=machine_id,
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("r1"),
        closing_revision_id=RevisionId("r2"),
        opened_at=opened_at,
        closed_at=closed_at,
        lines=(
            ReconciliationLine(
                product_code="coffee",
                actual_prev=Decimal("0"),
                actual=Decimal("0"),
                calculated=Decimal("0"),
                delta=Decimal("0"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status=status,  # type: ignore[arg-type]
        ledger_posted=ledger_posted,
    )


def _sale(*, source_id: str, occurred_at: datetime) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=_MACHINE,
        product_code="coffee-1",
        quantity=Decimal("1"),
        occurred_at=occurred_at,
        ingested_at=_INGESTED,
        sale_kind="coffee",
        machine_code=_CODE,
    )


def _raw(*, source_id: str, occurred_at: datetime, line: int) -> RawKitSaleIdentity:
    return RawKitSaleIdentity(
        source_id=source_id,
        kit_vending_machine_id=10,
        vending_machine_name=f"Аппарат {_CODE}",
        vending_machine_code=_CODE,
        occurred_at=occurred_at,
        line_number=line,
        matrix_id=100,
        goods_name="Кофе 2301",
    )


def _row(*, source_id: str, occurred_at: datetime) -> KitVendingSaleRow:
    return KitVendingSaleRow(
        source_id=source_id,
        vending_machine_code=_CODE,
        product_code="coffee-1",
        quantity=Decimal("1"),
        occurred_at=occurred_at,
        sale_kind="coffee",
        kit_matrix_id=100,
        kit_vending_machine_id=10,
        kit_line_number=1,
        price=Decimal("50"),
    )


@dataclass
class _FakeKitGateway:
    raw: list[RawKitSaleIdentity]
    resolve_results: dict[str, KitSaleResolveSuccess | KitSaleResolveSkip]
    resolve_calls: list[str] = field(default_factory=list)

    def fetch_raw_window(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
    ) -> list[RawKitSaleIdentity]:
        _ = from_date, to_date
        return list(self.raw)

    def resolve(self, source_id: str) -> KitSaleResolveSuccess | KitSaleResolveSkip:
        self.resolve_calls.append(source_id)
        return self.resolve_results[source_id]


@dataclass
class _FakeRefresh:
    calls: int = 0

    def execute(self, *, machine_id: MachineId | None = None) -> object:
        _ = machine_id
        self.calls += 1
        return object()


def test_sales_verify_resolve_called_only_on_missing() -> None:
    sales_store = InMemoryMachineSalesStore()
    sales_store.insert_if_absent(
        _sale(source_id=_SOURCE_A, occurred_at=datetime(2026, 8, 2, 10, 0, tzinfo=UTC)),
    )
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_period())
    gateway = _FakeKitGateway(
        raw=[
            _raw(
                source_id=_SOURCE_A,
                occurred_at=datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
                line=1,
            ),
            _raw(
                source_id=_SOURCE_B,
                occurred_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                line=2,
            ),
        ],
        resolve_results={
            _SOURCE_B: KitSaleResolveSuccess(
                row=_row(
                    source_id=_SOURCE_B,
                    occurred_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                ),
            ),
        },
    )
    refresh = _FakeRefresh()
    use_case = VerifyPortionSales(
        sales_store=sales_store,
        kit_gateway=gateway,
        skip_store=InMemoryMachineSaleSkipStore(),
        reconciliation_repo=repo,
        code_resolver=MappingVendingMachineCodeResolver({_CODE: _MACHINE}),
        refresh=refresh,
        now=lambda: _INGESTED,
    )

    use_case.execute(technician_id=_TECH, cutoff=_CUTOFF)

    assert gateway.resolve_calls == [_SOURCE_B]
    window = sales_store.find_in_window(
        _MACHINE,
        opened_at=_OPENED,
        closed_at=_CUTOFF,
    )
    source_ids = {sale.source_id for sale in window}
    assert source_ids == {_SOURCE_A, _SOURCE_B}
    assert refresh.calls == 1


def _use_case(
    *,
    sales_store: InMemoryMachineSalesStore,
    repo: InMemoryPeriodReconciliationRepository,
    gateway: _FakeKitGateway,
    skip_store: InMemoryMachineSaleSkipStore,
    refresh: _FakeRefresh,
) -> VerifyPortionSales:
    return VerifyPortionSales(
        sales_store=sales_store,
        kit_gateway=gateway,
        skip_store=skip_store,
        reconciliation_repo=repo,
        code_resolver=MappingVendingMachineCodeResolver({_CODE: _MACHINE}),
        refresh=refresh,
        now=lambda: _INGESTED,
    )


def test_sales_verify_holding_fails_after_skip_upsert() -> None:
    sales_store = InMemoryMachineSalesStore()
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_period())
    skip_store = InMemoryMachineSaleSkipStore()
    holding_source = "kit:10:2026-08-03T11:00:00:3:100"
    non_holding_source = "kit:10:2026-08-03T12:00:00:4:100"
    gateway = _FakeKitGateway(
        raw=[
            _raw(
                source_id=holding_source,
                occurred_at=datetime(2026, 8, 3, 11, 0, tzinfo=UTC),
                line=3,
            ),
            _raw(
                source_id=non_holding_source,
                occurred_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
                line=4,
            ),
        ],
        resolve_results={
            holding_source: KitSaleResolveSkip(
                reason_class="critical_product_resolve",
                holding=True,
            ),
            non_holding_source: KitSaleResolveSkip(
                reason_class="line_neg_1",
                holding=False,
            ),
        },
    )
    refresh = _FakeRefresh()
    use_case = _use_case(
        sales_store=sales_store,
        repo=repo,
        gateway=gateway,
        skip_store=skip_store,
        refresh=refresh,
    )

    with pytest.raises(VerifyPortionSalesHoldingError):
        use_case.execute(technician_id=_TECH, cutoff=_CUTOFF)

    holding_skip = skip_store.get(holding_source)
    assert holding_skip is not None
    assert holding_skip.reason_class == "critical_product_resolve"
    non_holding_skip = skip_store.get(non_holding_source)
    assert non_holding_skip is not None
    assert non_holding_skip.reason_class == "line_neg_1"
    assert refresh.calls == 0

    # non-holding only → no raise; skip upsert line_neg_1
    skip_store_nh = InMemoryMachineSaleSkipStore()
    gateway_nh = _FakeKitGateway(
        raw=[
            _raw(
                source_id=non_holding_source,
                occurred_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
                line=4,
            ),
        ],
        resolve_results={
            non_holding_source: KitSaleResolveSkip(
                reason_class="line_neg_1",
                holding=False,
            ),
        },
    )
    refresh_nh = _FakeRefresh()
    use_case_nh = _use_case(
        sales_store=InMemoryMachineSalesStore(),
        repo=repo,
        gateway=gateway_nh,
        skip_store=skip_store_nh,
        refresh=refresh_nh,
    )

    use_case_nh.execute(technician_id=_TECH, cutoff=_CUTOFF)

    only_nh = skip_store_nh.get(non_holding_source)
    assert only_nh is not None
    assert only_nh.reason_class == "line_neg_1"
    assert refresh_nh.calls == 1


def test_sales_verify_import_missing_clears_skip() -> None:
    sales_store = InMemoryMachineSalesStore()
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_period())
    skip_store = InMemoryMachineSaleSkipStore()
    seen = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    skip_store.upsert(
        MachineSaleSkip(
            source_id=_SOURCE_B,
            reason_class="critical_product_resolve",
            kit_vending_machine_id=10,
            vending_machine_name=f"Аппарат {_CODE}",
            occurred_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
            line_number=2,
            matrix_id=100,
            goods_name="Кофе 2301",
            external_id=None,
            first_seen_at=seen,
            last_seen_at=seen,
        ),
    )
    gateway = _FakeKitGateway(
        raw=[
            _raw(
                source_id=_SOURCE_B,
                occurred_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                line=2,
            ),
        ],
        resolve_results={
            _SOURCE_B: KitSaleResolveSuccess(
                row=_row(
                    source_id=_SOURCE_B,
                    occurred_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                ),
            ),
        },
    )
    use_case = _use_case(
        sales_store=sales_store,
        repo=repo,
        gateway=gateway,
        skip_store=skip_store,
        refresh=_FakeRefresh(),
    )

    use_case.execute(technician_id=_TECH, cutoff=_CUTOFF)

    assert skip_store.get(_SOURCE_B) is None
    window = sales_store.find_in_window(
        _MACHINE,
        opened_at=_OPENED,
        closed_at=_CUTOFF,
    )
    assert {sale.source_id for sale in window} == {_SOURCE_B}


def test_sales_verify_refreshes_pending() -> None:
    sales_store = InMemoryMachineSalesStore()
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_period())
    gateway = _FakeKitGateway(raw=[], resolve_results={})
    refresh = _FakeRefresh()
    use_case = _use_case(
        sales_store=sales_store,
        repo=repo,
        gateway=gateway,
        skip_store=InMemoryMachineSaleSkipStore(),
        refresh=refresh,
    )

    use_case.execute(technician_id=_TECH, cutoff=_CUTOFF)

    assert refresh.calls == 1


def test_sales_verify_membership_aligned_to_period_windows() -> None:
    # Sale already in mongo with occurred_at ∈ (period.closed_at, cutoff];
    # Kit raw has the same row — must not count as missing / trigger resolve.
    after_close = datetime(2026, 8, 5, 11, 0, tzinfo=UTC)
    source_after = "kit:10:2026-08-05T11:00:00:9:100"
    sales_store = InMemoryMachineSalesStore()
    sales_store.insert_if_absent(_sale(source_id=source_after, occurred_at=after_close))
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_period())
    gateway = _FakeKitGateway(
        raw=[_raw(source_id=source_after, occurred_at=after_close, line=9)],
        resolve_results={
            source_after: KitSaleResolveSkip(
                reason_class="critical_product_resolve",
                holding=True,
            ),
        },
    )
    refresh = _FakeRefresh()
    use_case = _use_case(
        sales_store=sales_store,
        repo=repo,
        gateway=gateway,
        skip_store=InMemoryMachineSaleSkipStore(),
        refresh=refresh,
    )

    use_case.execute(technician_id=_TECH, cutoff=_CUTOFF)

    assert gateway.resolve_calls == []
    assert refresh.calls == 1


def test_sales_verify_pending_sales_within_cutoff_in_scope() -> None:
    # pending_sales with closed_at ≤ cutoff enters scope → missing resolves/imports.
    sales_store = InMemoryMachineSalesStore()
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(
        _period(
            period_id="pending-in",
            status="pending_sales",
            ledger_posted=False,
        ),
    )
    gateway = _FakeKitGateway(
        raw=[
            _raw(
                source_id=_SOURCE_B,
                occurred_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                line=2,
            ),
        ],
        resolve_results={
            _SOURCE_B: KitSaleResolveSuccess(
                row=_row(
                    source_id=_SOURCE_B,
                    occurred_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                ),
            ),
        },
    )
    use_case = _use_case(
        sales_store=sales_store,
        repo=repo,
        gateway=gateway,
        skip_store=InMemoryMachineSaleSkipStore(),
        refresh=_FakeRefresh(),
    )

    use_case.execute(technician_id=_TECH, cutoff=_CUTOFF)

    assert gateway.resolve_calls == [_SOURCE_B]
    window = sales_store.find_in_window(
        _MACHINE,
        opened_at=_OPENED,
        closed_at=_CUTOFF,
    )
    assert {sale.source_id for sale in window} == {_SOURCE_B}


def test_sales_verify_deferred_closed_at_after_cutoff_out_of_scope() -> None:
    # pending with closed_at > cutoff is deferred — Kit sale on that machine must not resolve.
    deferred_open = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    deferred_close = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    sale_at = datetime(2026, 8, 5, 11, 0, tzinfo=UTC)
    deferred_source = "kit:10:2026-08-05T11:00:00:8:100"
    sales_store = InMemoryMachineSalesStore()
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(
        _period(
            period_id="pending-deferred",
            status="pending_sales",
            ledger_posted=False,
            opened_at=deferred_open,
            closed_at=deferred_close,
        ),
    )
    gateway = _FakeKitGateway(
        raw=[_raw(source_id=deferred_source, occurred_at=sale_at, line=8)],
        resolve_results={
            deferred_source: KitSaleResolveSuccess(
                row=_row(source_id=deferred_source, occurred_at=sale_at),
            ),
        },
    )
    refresh = _FakeRefresh()
    use_case = _use_case(
        sales_store=sales_store,
        repo=repo,
        gateway=gateway,
        skip_store=InMemoryMachineSaleSkipStore(),
        refresh=refresh,
    )

    use_case.execute(technician_id=_TECH, cutoff=_CUTOFF)

    assert gateway.resolve_calls == []
    assert refresh.calls == 1
    assert (
        sales_store.find_in_window(
            _MACHINE,
            opened_at=deferred_open,
            closed_at=deferred_close,
        )
        == ()
    )
