from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.inventory_reconciliation.kitvending import KitVendingSaleRow
from src.application.inventory_reconciliation.period_errors import PeriodReconciliationNotFound
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)


def test_in_memory_machine_sales_store_window_and_dedupe() -> None:
    store = InMemoryMachineSalesStore()
    opened = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
    inside = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    ingested = datetime(2026, 6, 5, 13, 0, tzinfo=UTC)
    sale = MachineSale(
        source_id="kv-1",
        machine_id=MachineId("vm-01"),
        product_code="coffee-1",
        quantity=Decimal("2"),
        occurred_at=inside,
        ingested_at=ingested,
    )

    assert store.insert_if_absent(sale) is True
    assert store.insert_if_absent(sale) is False
    assert store.last_occurred_at(MachineId("vm-01")) == inside

    in_window = store.find_in_window(
        MachineId("vm-01"),
        opened_at=opened,
        closed_at=closed,
    )
    assert len(in_window) == 1
    assert in_window[0].quantity == Decimal("2")


def test_max_occurred_at_global_across_machines() -> None:
    store = InMemoryMachineSalesStore()
    earlier = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    later = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    ingested = datetime(2026, 6, 5, 13, 0, tzinfo=UTC)
    store.insert_if_absent(
        MachineSale(
            source_id="kv-1",
            machine_id=MachineId("vm-01"),
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=earlier,
            ingested_at=ingested,
        ),
    )
    store.insert_if_absent(
        MachineSale(
            source_id="kv-2",
            machine_id=MachineId("vm-02"),
            product_code="coffee-2",
            quantity=Decimal("1"),
            occurred_at=later,
            ingested_at=ingested,
        ),
    )

    assert store.max_occurred_at() == later


def test_max_occurred_at_returns_none_when_empty() -> None:
    store = InMemoryMachineSalesStore()

    assert store.max_occurred_at() is None


def test_find_in_window_respects_half_open_interval() -> None:
    store = InMemoryMachineSalesStore()
    opened = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
    at_open = opened
    inside = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    at_closed = closed
    ingested = datetime(2026, 6, 5, 13, 0, tzinfo=UTC)

    for source_id, occurred_at in (
        ("at-open", at_open),
        ("inside", inside),
        ("at-closed", at_closed),
    ):
        store.insert_if_absent(
            MachineSale(
                source_id=source_id,
                machine_id=MachineId("vm-01"),
                product_code="coffee-1",
                quantity=Decimal("1"),
                occurred_at=occurred_at,
                ingested_at=ingested,
            ),
        )

    in_window = store.find_in_window(
        MachineId("vm-01"),
        opened_at=opened,
        closed_at=closed,
    )
    source_ids = {sale.source_id for sale in in_window}
    assert source_ids == {"inside", "at-closed"}
    assert "at-open" not in source_ids


def test_in_memory_period_reconciliation_repository() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    snapshot = ResponsibilityPeriodReconciliation(
        period_id="rev-1:rev-2",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        closed_at=datetime(2026, 6, 8, 10, 0, tzinfo=UTC),
        lines=(),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=True,
        reconciled=False,
    )
    repo.save(snapshot)

    assert repo.get_by_period_id("rev-1:rev-2") == snapshot
    assert len(repo.list_posted_unreconciled(technician_id=TechnicianId("tech-a"))) == 1
    assert len(repo.list_by_status(status="complete", machine_id=MachineId("vm-01"))) == 1

    repo.mark_reconciled(("rev-1:rev-2",))
    assert repo.reconciled_periods == [("rev-1:rev-2",)]
    updated = repo.get_by_period_id("rev-1:rev-2")
    assert updated is not None
    assert updated.reconciled is True


def _period_snapshot(*, period_id: str) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        closed_at=datetime(2026, 6, 8, 10, 0, tzinfo=UTC),
        lines=(),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=True,
        reconciled=False,
    )


def test_in_memory_mark_reconciled_noop_for_empty_period_ids() -> None:
    repo = InMemoryPeriodReconciliationRepository()

    repo.mark_reconciled(())

    assert repo.reconciled_periods == []


def test_in_memory_mark_reconciled_is_atomic_for_batch() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_period_snapshot(period_id="rev-1:rev-2"))
    repo.save(_period_snapshot(period_id="rev-2:rev-3"))

    with pytest.raises(PeriodReconciliationNotFound, match="rev-missing"):
        repo.mark_reconciled(("rev-1:rev-2", "rev-missing"))

    assert repo.get_by_period_id("rev-1:rev-2") is not None
    assert repo.get_by_period_id("rev-1:rev-2").reconciled is False
    assert repo.get_by_period_id("rev-2:rev-3").reconciled is False
    assert repo.reconciled_periods == []


def test_stub_kitvending_client_fetch_all() -> None:
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T12:00:00Z",
            },
        ],
    )
    rows = client.fetch_all(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert len(rows) == 1
    assert isinstance(rows[0], KitVendingSaleRow)
    assert rows[0].quantity == Decimal("2")


def test_in_memory_technician_settlement_repository() -> None:
    event_store = InMemoryTechnicianSettlementEventStore()
    repo = InMemoryTechnicianSettlementRepository(event_store=event_store)
    aggregate = repo.get(TechnicianId("tech-a"))
    assert aggregate.net_balance_by_sku() == {}
    assert repo.events == []
