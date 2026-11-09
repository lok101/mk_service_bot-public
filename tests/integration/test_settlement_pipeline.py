from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pymongo.database import Database
from tests.integration.settlement_pipeline_helpers import (
    COMPONENT_CODE,
    assert_finalize_events,
    assert_period_accountability_recorded,
    assert_reconciliation_outbox_processed,
    assert_settlement_balance,
    assert_snapshot,
    drain_outbox_sync,
    insert_bundle_sale,
    post_closing_revision,
    post_loading,
    post_opening_revision,
    post_warehouse_inventory,
    seed_latte_bom,
)
from tests.integration.stack import build_webhook_pipeline_stack

from src.application.technician_warehouse.ports import TechnicianWarehouseDelta
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.infrastructure.testing import TEST_TECHNICIAN_ID
from src.infrastructure.testing.settlement_fakes import FakeTechnicianWarehouseDeltaPort

pytestmark = pytest.mark.integration


def test_settlement_v2_pipeline(mongo_database: Database) -> None:
    inv_moment = datetime(2026, 6, 19, 10, 0, tzinfo=UTC)
    warehouse_delta_port = FakeTechnicianWarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="inv-integration-1",
            inventory_moment=inv_moment,
            warehouse_delta_by_sku={
                COMPONENT_CODE: Decimal("1"),
            },
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=(),
        ),
    )
    stack = build_webhook_pipeline_stack(
        mongo_database,
        warehouse_delta_port=warehouse_delta_port,
    )

    timeline = post_opening_revision(stack, nonce="v2-rev-1")
    post_loading(stack, timeline, nonce="v2-load-1")
    seed_latte_bom(stack)
    insert_bundle_sale(stack, timeline, source_id="kv-v2-1")

    closing = post_closing_revision(
        stack,
        timeline,
        closing_coffee="88",
        nonce="v2-rev-2",
    )
    drain_outbox_sync(stack)

    assert_snapshot(
        stack,
        closing.period_id,
        status="complete",
        ledger_posted=True,
        reconciled=False,
        delta=Decimal("-2"),
    )
    assert_reconciliation_outbox_processed(mongo_database, closing.event_id)
    accountability = assert_period_accountability_recorded(stack, period_id=closing.period_id)
    assert accountability.delta_by_sku["coffee-1"] == Decimal("-2")
    assert_settlement_balance(stack, product_code="coffee-1", expected=Decimal("-2"))

    assert (
        post_warehouse_inventory(
            stack,
            technician_id=TEST_TECHNICIAN_ID,
            coffee="10",
            nonce="v2-wh-inv",
            submitted_at=inv_moment,
        ).status_code
        == 200
    )
    warehouse = stack.warehouse_repository.get(TechnicianId(TEST_TECHNICIAN_ID.value))
    assert warehouse.latest_inventory_id is not None
    assert warehouse_delta_port.delta is not None
    warehouse_delta_port.delta = TechnicianWarehouseDelta(
        warehouse_inventory_id=warehouse.latest_inventory_id,
        inventory_moment=inv_moment,
        warehouse_delta_by_sku=dict(warehouse_delta_port.delta.warehouse_delta_by_sku),
        calculated_stock_by_sku={},
        actual_stock_by_sku={},
        transfer_refs=(),
        unmatched_products=(),
    )

    deferred_period_id = "rev-deferred-open:rev-deferred-close"
    stack.reconciliation_repo.save(
        ResponsibilityPeriodReconciliation(
            period_id=deferred_period_id,
            machine_id=MachineId("vm-deferred"),
            responsible_technician_id=TechnicianId(TEST_TECHNICIAN_ID.value),
            opening_revision_id=RevisionId("rev-deferred-open"),
            closing_revision_id=RevisionId("rev-deferred-close"),
            opened_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
            closed_at=datetime(2026, 6, 25, 10, 0, tzinfo=UTC),
            lines=(
                ReconciliationLine(
                    product_code="coffee-1",
                    actual_prev=Decimal("0"),
                    actual=Decimal("0"),
                    calculated=Decimal("0"),
                    delta=Decimal("-1"),
                ),
            ),
            sales_lines=(),
            load_count=0,
            status="complete",
            ledger_posted=True,
            reconciled=False,
        ),
    )

    preview = stack.preview_reconciliation.execute(
        technician_id=TechnicianId(TEST_TECHNICIAN_ID.value),
    )
    assert preview.residual_by_sku["coffee-1"] == Decimal("-1")

    result = stack.finalize_reconciliation.execute(
        technician_id=TechnicianId(TEST_TECHNICIAN_ID.value),
    )
    assert result.period_ids == (closing.period_id,)
    assert deferred_period_id in result.deferred_period_ids

    assert_snapshot(
        stack,
        closing.period_id,
        status="complete",
        ledger_posted=True,
        reconciled=True,
    )
    deferred = stack.reconciliation_repo.get_by_period_id(deferred_period_id)
    assert deferred is not None
    assert deferred.reconciled is False
    assert stack.residual_repo.count_all() == 1
    assert_settlement_balance(stack, product_code="coffee-1", expected=Decimal("0"))
    assert_finalize_events(stack)


def test_settlement_v2_pending_sales_then_refresh(mongo_database: Database) -> None:
    stack = build_webhook_pipeline_stack(mongo_database)

    timeline = post_opening_revision(stack, nonce="pending-v2-rev-1")
    post_loading(stack, timeline, nonce="pending-v2-load-1")
    seed_latte_bom(stack)

    closing = post_closing_revision(
        stack,
        timeline,
        closing_coffee="88",
        nonce="pending-v2-rev-2",
    )
    drain_outbox_sync(stack)

    assert_snapshot(
        stack,
        closing.period_id,
        status="pending_sales",
        ledger_posted=False,
        reconciled=False,
    )
    assert_reconciliation_outbox_processed(mongo_database, closing.event_id)

    insert_bundle_sale(stack, timeline, source_id="kv-pending-v2-1")
    stack.refresh_pending.execute()
    drain_outbox_sync(stack)

    assert_snapshot(
        stack,
        closing.period_id,
        status="complete",
        ledger_posted=True,
        reconciled=False,
        delta=Decimal("-2"),
    )
