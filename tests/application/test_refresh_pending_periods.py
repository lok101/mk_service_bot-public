from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.close_period_helpers import (
    CLOSED,
    OPENED,
    _default_coffee_bom,
    build_close_period_deps,
)

from src.application.inventory_reconciliation.refresh_pending import (
    RefreshPendingPeriodReconciliations,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
)


def _pending_snapshot() -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id="rev-1:rev-2",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=OPENED,
        closed_at=CLOSED,
        lines=(),
        sales_lines=(),
        load_count=0,
        status="pending_sales",
    )


def _refresh_from_deps(
    *,
    repo: InMemoryPeriodReconciliationRepository,
    sales_store: InMemoryMachineSalesStore,
    recipe_repo: InMemoryCoffeeRecipeRepository | None = None,
) -> RefreshPendingPeriodReconciliations:
    form_store, history, _, _ = build_close_period_deps()
    products, recipes = _default_coffee_bom()
    return RefreshPendingPeriodReconciliations(
        repo=repo,
        sales_store=sales_store,
        coffee_recipe_repo=recipe_repo or recipes,
        domain_product_store=products,
        form_submission_store=form_store,
        revision_history=history,
        tolerance_seconds=0,
    )


def test_refresh_returns_transitioned_on_complete() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    store = InMemoryMachineSalesStore()
    repo.save(_pending_snapshot())
    store.insert_if_absent(
        MachineSale(
            source_id="kv-late",
            machine_id=MachineId("vm-01"),
            product_code="2301",
            quantity=Decimal("1"),
            occurred_at=CLOSED,
            ingested_at=datetime(2026, 6, 8, 11, 0, tzinfo=UTC),
            sale_kind="coffee",
        ),
    )
    refresh = _refresh_from_deps(repo=repo, sales_store=store)

    result = refresh.execute(machine_id=MachineId("vm-01"))

    updated = repo.get_by_period_id("rev-1:rev-2")
    assert updated is not None
    assert updated.status == "complete"
    assert updated.lines
    assert updated.load_count == 1
    assert tuple(s.period_id for s in result.transitioned_to_complete) == ("rev-1:rev-2",)


def test_refresh_no_transition_when_still_pending() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    store = InMemoryMachineSalesStore()
    repo.save(_pending_snapshot())
    store.insert_if_absent(
        MachineSale(
            source_id="kv-early",
            machine_id=MachineId("vm-01"),
            product_code="2301",
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 6, 8, 9, 30, tzinfo=UTC),
            sale_kind="coffee",
        ),
    )
    refresh = _refresh_from_deps(repo=repo, sales_store=store)

    result = refresh.execute(machine_id=MachineId("vm-01"))

    assert result.transitioned_to_complete == ()


def test_refresh_skips_when_already_posted() -> None:
    from dataclasses import replace

    repo = InMemoryPeriodReconciliationRepository()
    store = InMemoryMachineSalesStore()
    repo.save(replace(_pending_snapshot(), ledger_posted=True))
    store.insert_if_absent(
        MachineSale(
            source_id="kv-late",
            machine_id=MachineId("vm-01"),
            product_code="2301",
            quantity=Decimal("1"),
            occurred_at=CLOSED,
            ingested_at=datetime(2026, 6, 8, 11, 0, tzinfo=UTC),
            sale_kind="coffee",
        ),
    )
    refresh = _refresh_from_deps(repo=repo, sales_store=store)

    result = refresh.execute(machine_id=MachineId("vm-01"))

    assert result.transitioned_to_complete == ()


def test_recalculate_complete_when_global_cursor_covers() -> None:
    # happy: cursor past closed_at, no sales on machine
    repo = InMemoryPeriodReconciliationRepository()
    store = InMemoryMachineSalesStore()
    repo.save(_pending_snapshot())
    store.save_global_cursor(CLOSED)
    refresh = _refresh_from_deps(repo=repo, sales_store=store)

    result = refresh.execute(machine_id=MachineId("vm-01"))

    updated = repo.get_by_period_id("rev-1:rev-2")
    assert updated is not None
    assert updated.status == "complete"
    assert tuple(s.period_id for s in result.transitioned_to_complete) == ("rev-1:rev-2",)
