from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pymongo.database import Database
from tests.integration.settlement_pipeline_helpers import (
    assert_snapshot,
    drain_handler_sync,
    drain_outbox_sync,
    external_supply_move,
    post_warehouse_inventory,
    post_warehouse_loading,
)
from tests.integration.stack import build_warehouse_settlement_stack

from src.application.outbox.handler_ids import TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_warehouse.ports import ExternalWarehouseMove
from src.domain.ids import AccountabilityId, MachineId, RevisionId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.product_catalog import ProductUnit
from src.domain.technician_settlement.aggregate import RecordPeriodAccountability
from src.infrastructure.testing import TEST_TECHNICIAN_ID, seed_test_machine_revision_events

pytestmark = pytest.mark.integration

_TECHNICIAN_ID = TEST_TECHNICIAN_ID
_MACHINE_ID = MachineId("vm-01")
_BASELINE_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_SUPPLY_AT = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
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


def _supply_move(*, product_code: str) -> ExternalWarehouseMove:
    return external_supply_move(
        document_id="move-unknown",
        source_store="main",
        target_store=_TECHNICIAN_ID.value,
        sku_code=product_code,
        quantity=Decimal("1"),
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


def _sync_transfers(stack: object, *, anchor_at: datetime) -> None:
    asyncio.run(stack.warehouse_importer.execute(_TECHNICIAN_ID, anchor_at=anchor_at))


def test_warehouse_to_settlement_pipeline(mongo_database: Database) -> None:
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

    post_warehouse_loading(
        stack,
        technician_id=_TECHNICIAN_ID,
        machine_id=_MACHINE_ID,
        loading_coffee="4",
        nonce="wh-load-before",
        submitted_at=_BASELINE_AT - timedelta(hours=1),
    )
    drain_outbox_sync(stack)

    first = post_warehouse_inventory(
        stack,
        technician_id=_TECHNICIAN_ID,
        coffee="6",
        nonce="wh-inv-baseline",
        submitted_at=_BASELINE_AT,
    )
    assert first.status_code == 200

    post_warehouse_loading(
        stack,
        technician_id=_TECHNICIAN_ID,
        machine_id=_MACHINE_ID,
        loading_coffee="3",
        nonce="wh-load-after",
        submitted_at=_LOADING_AFTER_AT,
    )
    drain_outbox_sync(stack)

    # Ops: sync-transfers / lazy import before eligible form inventory count.
    _sync_transfers(stack, anchor_at=_SECOND_INV_AT)

    second = post_warehouse_inventory(
        stack,
        technician_id=_TECHNICIAN_ID,
        coffee="12",
        nonce="wh-inv-second",
        submitted_at=_SECOND_INV_AT,
    )
    assert second.status_code == 200

    preview = stack.preview_reconciliation.execute(
        technician_id=_TECHNICIAN_ID,
    )
    # baseline 6 + supply 10 - load 3 = calculated 13; actual 12 => delta -1
    assert preview.warehouse_delta_by_sku == {"coffee": Decimal("-1")}
    assert preview.residual_by_sku == {"coffee": Decimal("-1")}

    result = stack.finalize_reconciliation.execute(
        technician_id=_TECHNICIAN_ID,
    )
    assert result.warehouse_source == "domain_technician_warehouse"
    assert result.warehouse_inventory_id is not None
    assert_snapshot(
        stack,
        _PERIOD_ID,
        status="complete",
        ledger_posted=True,
        reconciled=True,
    )


def test_missing_visibility_ms_move_does_not_change_warehouse_delta(
    mongo_database: Database,
) -> None:
    stack = _warehouse_stack(mongo_database)
    seed_test_machine_revision_events(stack.event_store)

    post_warehouse_loading(
        stack,
        technician_id=_TECHNICIAN_ID,
        machine_id=_MACHINE_ID,
        loading_coffee="3",
        nonce="wh-load-visibility",
        submitted_at=_LOADING_AFTER_AT,
    )
    drain_handler_sync(stack, TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID)

    warehouse = stack.warehouse_repository.get(_TECHNICIAN_ID)
    assert warehouse.calculated_stock_since_baseline() == {"coffee": Decimal("-3")}


def test_non_domain_transfer_product_does_not_block_finalize(
    mongo_database: Database,
) -> None:
    """edge: MS line вне catalog обрезается; finalize не blocked кодом unknown."""
    stack = _warehouse_stack(
        mongo_database,
        warehouse_moves=(_supply_move(product_code="unknown"),),
    )
    seed_test_machine_revision_events(stack.event_store)
    _seed_posted_period(stack)

    assert (
        post_warehouse_inventory(
            stack,
            technician_id=_TECHNICIAN_ID,
            coffee="6",
            nonce="wh-inv-unmatched-1",
            submitted_at=_BASELINE_AT,
        ).status_code
        == 200
    )
    assert (
        post_warehouse_inventory(
            stack,
            technician_id=_TECHNICIAN_ID,
            coffee="6",
            nonce="wh-inv-unmatched-2",
            submitted_at=_SECOND_INV_AT,
        ).status_code
        == 200
    )

    preview = stack.preview_reconciliation.execute(
        technician_id=_TECHNICIAN_ID,
    )
    assert preview.can_finalize is True
    assert list(preview.unmatched_products) == []
    assert "unknown" not in preview.blockers

    stack.finalize_reconciliation.execute(
        technician_id=_TECHNICIAN_ID,
    )


def test_empty_supply_codes_block_regular_preview_not_warehouse_form(
    mongo_database: Database,
) -> None:
    stack = _warehouse_stack(mongo_database, supply_store_codes=())
    seed_test_machine_revision_events(stack.event_store)
    _seed_posted_period(stack)

    response = post_warehouse_inventory(
        stack,
        technician_id=_TECHNICIAN_ID,
        coffee="6",
        nonce="wh-inv-empty-supply",
        submitted_at=_BASELINE_AT,
    )
    assert response.status_code == 200

    preview = stack.preview_reconciliation.execute(
        technician_id=_TECHNICIAN_ID,
    )
    assert any("SUPPLY_STORE_CODES" in blocker for blocker in preview.blockers)
    assert preview.can_finalize is False
