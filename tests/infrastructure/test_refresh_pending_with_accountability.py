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
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale
from src.infrastructure.composition.refresh_pending_with_accountability import (
    RefreshPendingWithAccountability,
)
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)


def test_facade_posts_accountability_on_transition() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    store = InMemoryMachineSalesStore()
    repo.save(
        ResponsibilityPeriodReconciliation(
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
        ),
    )
    store.insert_if_absent(
        MachineSale(
            source_id="kv-late",
            machine_id=MachineId("vm-01"),
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=CLOSED,
            ingested_at=datetime(2026, 6, 8, 11, 0, tzinfo=UTC),
            sale_kind="coffee",
        ),
    )
    form_store, history, _, _ = build_close_period_deps()
    _products, _recipes = _default_coffee_bom()

    refresh = RefreshPendingPeriodReconciliations(
        repo=repo,
        sales_store=store,
        coffee_recipe_repo=_recipes,
        domain_product_store=_products,
        form_submission_store=form_store,
        revision_history=history,
        tolerance_seconds=0,
    )
    settlement_repo = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    facade = RefreshPendingWithAccountability(
        refresh=refresh,
        post_accountability=PostPeriodAccountability(
            settlement_executor=TechnicianSettlementExecutor(repository=settlement_repo),
            reconciliation_repo=repo,
        ),
    )

    facade.execute(machine_id=MachineId("vm-01"))

    assert repo.ledger_posted_periods == ["rev-1:rev-2"]
    assert settlement_repo.get(TechnicianId("tech-a")).net_balance_by_sku() == {
        "coffee-1": Decimal("-29"),
    }
