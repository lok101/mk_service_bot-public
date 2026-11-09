from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pymongo.database import Database
from tests.integration.settlement_pipeline_helpers import (
    assert_snapshot,
    drain_outbox_sync,
    external_supply_move,
    post_warehouse_inventory,
    post_warehouse_loading,
)
from tests.integration.stack import build_warehouse_settlement_stack

from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.reconciliation_planner import ReconciliationBlocked
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
)
from src.domain.ids import AccountabilityId, MachineId, RevisionId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.product_catalog import ProductUnit
from src.domain.technician_settlement.aggregate import RecordPeriodAccountability
from src.infrastructure.mongodb.reconciliation_drafts import MongoReconciliationDraftStore
from src.infrastructure.testing import TEST_TECHNICIAN_ID, seed_test_machine_revision_events

pytestmark = pytest.mark.integration

_TECHNICIAN_ID = TEST_TECHNICIAN_ID
_MACHINE_ID = MachineId("vm-01")
_BASELINE_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_LOADING_AFTER_AT = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)
_SECOND_INV_AT = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
_PERIOD_ID = "wh-open:wh-close"


def _warehouse_stack(mongo_database: Database, **kwargs: object):
    return build_warehouse_settlement_stack(
        mongo_database,
        product_mapping={"Кофе": "coffee"},
        product_aliases={"rich-coffee-alias": "coffee"},
        pack_size=Decimal("1"),
        unit=ProductUnit.PIECE,
        **kwargs,
    )


def _seed_posted_period(stack: object) -> None:
    snapshot = ResponsibilityPeriodReconciliation(
        period_id=_PERIOD_ID,
        machine_id=_MACHINE_ID,
        responsible_technician_id=_TECHNICIAN_ID,
        opening_revision_id=RevisionId("wh-open"),
        closing_revision_id=RevisionId("wh-close"),
        opened_at=_BASELINE_AT - timedelta(days=10),
        closed_at=_BASELINE_AT - timedelta(days=1),
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
                delta_by_sku={},
                closed_at=snapshot.closed_at,
            ),
        ),
    )
    stack.reconciliation_repo.mark_ledger_posted(_PERIOD_ID)


def _install_counting_importer(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[Any, datetime]]:
    """Count ImportTechnicianWarehouseTransfers.execute calls (local helper, not stack.py)."""
    calls: list[tuple[Any, datetime]] = []
    original_execute = ImportTechnicianWarehouseTransfers.execute

    async def _execute(
        self: ImportTechnicianWarehouseTransfers,
        technician_id: Any,
        *,
        anchor_at: datetime,
    ) -> Any:
        calls.append((technician_id, anchor_at))
        return await original_execute(self, technician_id, anchor_at=anchor_at)

    monkeypatch.setattr(ImportTechnicianWarehouseTransfers, "execute", _execute)
    return calls


def test_integration_preview_draft_finalize_importer_once(
    mongo_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import_calls = _install_counting_importer(monkeypatch)
    stack = _warehouse_stack(
        mongo_database,
        warehouse_moves=(
            external_supply_move(
                document_id="move-1",
                source_store="main",
                target_store=_TECHNICIAN_ID.value,
                sku_code="rich-coffee-alias",
                quantity=Decimal("10"),
            ),
        ),
        supply_store_codes=("main",),
    )
    seed_test_machine_revision_events(stack.event_store)
    _seed_posted_period(stack)
    draft_store = MongoReconciliationDraftStore.from_collection(
        mongo_database["reconciliation_drafts"],
    )

    post_warehouse_loading(
        stack,
        technician_id=_TECHNICIAN_ID,
        machine_id=_MACHINE_ID,
        loading_coffee="4",
        nonce="draft-load-before",
        submitted_at=_BASELINE_AT - timedelta(hours=1),
    )
    drain_outbox_sync(stack)

    assert (
        post_warehouse_inventory(
            stack,
            technician_id=_TECHNICIAN_ID,
            coffee="6",
            nonce="draft-inv-baseline",
            submitted_at=_BASELINE_AT,
        ).status_code
        == 200
    )

    post_warehouse_loading(
        stack,
        technician_id=_TECHNICIAN_ID,
        machine_id=_MACHINE_ID,
        loading_coffee="3",
        nonce="draft-load-after",
        submitted_at=_LOADING_AFTER_AT,
    )
    drain_outbox_sync(stack)

    assert (
        post_warehouse_inventory(
            stack,
            technician_id=_TECHNICIAN_ID,
            coffee="12",
            nonce="draft-inv-second",
            submitted_at=_SECOND_INV_AT,
        ).status_code
        == 200
    )

    import_calls.clear()
    preview = stack.preview_reconciliation.execute(
        technician_id=_TECHNICIAN_ID,
    )
    assert preview.can_finalize is True
    draft = draft_store.get(_TECHNICIAN_ID.value, "inventory")
    assert draft is not None
    assert draft.kind == "inventory"
    assert draft.warehouse_inventory_id == preview.warehouse_inventory_id
    preview_import_count = len(import_calls)
    assert preview_import_count >= 1

    result = stack.finalize_reconciliation.execute(technician_id=_TECHNICIAN_ID)
    assert len(import_calls) == preview_import_count
    assert draft_store.get(_TECHNICIAN_ID.value, "inventory") is None
    assert result.warehouse_source == "domain_technician_warehouse"
    assert stack.warehouse_repository.has_finalized_transfers_for_session(
        _TECHNICIAN_ID,
        session_id=result.session_id.value,
    )
    assert_snapshot(
        stack,
        _PERIOD_ID,
        status="complete",
        ledger_posted=True,
        reconciled=True,
    )

    with pytest.raises(ReconciliationBlocked, match="no reconciliation draft"):
        stack.finalize_reconciliation.execute(technician_id=_TECHNICIAN_ID)
    assert len(import_calls) == preview_import_count
