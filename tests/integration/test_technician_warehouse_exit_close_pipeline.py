from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pymongo.database import Database
from tests.integration.settlement_pipeline_helpers import (
    external_supply_move,
    post_warehouse_inventory,
)
from tests.integration.stack import build_warehouse_settlement_stack

from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.exit_reconciliation import (
    FinalizeExitTechnicianReconciliation,
    PreviewExitTechnicianReconciliation,
)
from src.application.technician_settlement.list_technician_reconciliation_blockers import (
    ListTechnicianReconciliationBlockersResult,
)
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationBlocked,
)
from src.application.technician_warehouse.close_warehouse import CloseTechnicianWarehouse
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.domain.ids import AccountabilityId, MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.product_catalog import ProductUnit
from src.domain.technician_settlement.aggregate import RecordPeriodAccountability
from src.infrastructure.composition.adapters.warehouse_session_finalize import (
    WarehouseSessionFinalizeAdapter,
)
from src.infrastructure.testing import TEST_TECHNICIAN_ID
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore

pytestmark = pytest.mark.integration

_TECHNICIAN_ID = TEST_TECHNICIAN_ID
_MACHINE_ID = MachineId("vm-exit-01")
_BASELINE_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_RETURN_AT = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
_CLOSED_AT = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)
_PERIOD_ID = "exit-open:exit-close"


@dataclass
class _NoBlockers:
    def execute(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> ListTechnicianReconciliationBlockersResult:
        _ = checked_at
        return ListTechnicianReconciliationBlockersResult(
            technician_id=technician_id,
            technician_name="Tech",
            pending_sales=(),
            operational_open=(),
        )


def _warehouse_stack(mongo_database: Database, **kwargs: object):
    return build_warehouse_settlement_stack(
        mongo_database,
        product_mapping={"Кофе": "coffee"},
        pack_size=Decimal("1"),
        unit=ProductUnit.PIECE,
        **kwargs,
    )


def _seed_posted_period(stack: object) -> None:
    snapshot = ResponsibilityPeriodReconciliation(
        period_id=_PERIOD_ID,
        machine_id=_MACHINE_ID,
        responsible_technician_id=_TECHNICIAN_ID,
        opening_revision_id=RevisionId("exit-open"),
        closing_revision_id=RevisionId("exit-close"),
        opened_at=_BASELINE_AT - timedelta(days=10),
        closed_at=_BASELINE_AT - timedelta(days=1),
        lines=(
            ReconciliationLine(
                product_code="coffee",
                actual_prev=Decimal("0"),
                actual=Decimal("0"),
                calculated=Decimal("1"),
                delta=Decimal("-1"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=False,
        reconciled=False,
    )
    stack.reconciliation_repo.save(snapshot)
    executor = TechnicianSettlementExecutor(repository=stack.settlement_repository)
    executor.execute(
        _TECHNICIAN_ID,
        lambda aggregate: aggregate.record_period_accountability(
            RecordPeriodAccountability(
                accountability_id=AccountabilityId(f"{_TECHNICIAN_ID.value}:{_PERIOD_ID}"),
                period_id=_PERIOD_ID,
                machine_id=_MACHINE_ID,
                delta_by_sku={"coffee": Decimal("-1")},
                closed_at=snapshot.closed_at,
            ),
        ),
    )
    stack.reconciliation_repo.mark_ledger_posted(_PERIOD_ID)


def test_warehouse_exit_close_then_exit_reconcile_finalize(
    mongo_database: Database,
) -> None:
    stack = _warehouse_stack(
        mongo_database,
        warehouse_moves=(
            external_supply_move(
                document_id="ret-exit-1",
                source_store=_TECHNICIAN_ID.value,
                target_store="main",
                sku_code="coffee",
                quantity=Decimal("5"),
                moment=_RETURN_AT,
            ),
        ),
        supply_store_codes=("main",),
    )
    warehouse_executor = TechnicianWarehouseExecutor(repository=stack.warehouse_repository)

    baseline = post_warehouse_inventory(
        stack,
        technician_id=_TECHNICIAN_ID,
        coffee="10",
        nonce="exit-inv-baseline",
        submitted_at=_BASELINE_AT,
    )
    assert baseline.status_code == 200

    close = CloseTechnicianWarehouse(
        executor=warehouse_executor,
        importer=stack.warehouse_importer,
    )
    asyncio.run(
        close.execute(
            technician_id=_TECHNICIAN_ID,
            closed_at=_CLOSED_AT,
            confirm=True,
        ),
    )
    warehouse = stack.warehouse_repository.get(_TECHNICIAN_ID)
    assert warehouse.is_closed() is True
    delta = warehouse.latest_warehouse_delta()
    assert delta is not None
    assert delta.actual_by_sku == {}

    _seed_posted_period(stack)

    draft_store = InMemoryReconciliationDraftStore()
    preview_exit = PreviewExitTechnicianReconciliation(
        warehouse_repository=stack.warehouse_repository,
        reconciliation_repo=stack.reconciliation_repo,
        blockers=_NoBlockers(),
        draft_store=draft_store,
    )
    preview_exit.build_preview(technician_id=_TECHNICIAN_ID)
    finalize_exit = FinalizeExitTechnicianReconciliation(
        warehouse_repository=stack.warehouse_repository,
        reconciliation_repo=stack.reconciliation_repo,
        settlement_executor=TechnicianSettlementExecutor(
            repository=stack.settlement_repository,
        ),
        settlement_repository=stack.settlement_repository,
        residual_repo=stack.residual_repo,
        warehouse_finalize=WarehouseSessionFinalizeAdapter(executor=warehouse_executor),
        draft_store=draft_store,
    )
    result = finalize_exit.execute(technician_id=_TECHNICIAN_ID)
    assert result.mode == "exit_warehouse_closed"
    assert (
        stack.reconciliation_repo.list_posted_unreconciled(
            technician_id=_TECHNICIAN_ID,
        )
        == []
    )
    assert stack.warehouse_repository.has_finalized_transfers_for_session(
        _TECHNICIAN_ID,
        session_id=result.session_id.value,
    )

    with pytest.raises(ReconciliationBlocked, match="exit-reconcile"):
        stack.preview_reconciliation.planner.plan(
            technician_id=_TECHNICIAN_ID,
        )
