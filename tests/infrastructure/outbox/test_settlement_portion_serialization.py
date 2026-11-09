from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import EventId, TechnicianId
from src.domain.technician_settlement.portion_events import (
    SettlementPortionReconcileRequested,
    SettlementPortionSalesVerifyRequested,
    SettlementPortionSyncTransfersRequested,
)
from src.infrastructure.outbox.serialization import (
    event_from_outbox_document,
    event_to_outbox_document,
)


def test_portion_event_id_roundtrip() -> None:
    tech = TechnicianId("t1")
    inv = "inv-abc"
    moment = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    event = SettlementPortionSyncTransfersRequested(
        event_id=EventId(f"portion:{tech.value}:{inv}:sync"),
        technician_id=tech,
        warehouse_inventory_id=inv,
        warehouse_inventory_moment=moment,
        occurred_at=moment,
    )
    doc = event_to_outbox_document(event)
    restored = event_from_outbox_document(doc)
    assert isinstance(restored, SettlementPortionSyncTransfersRequested)
    assert restored.event_id.value == "portion:t1:inv-abc:sync"
    assert restored.technician_id == tech
    assert restored.warehouse_inventory_id == inv
    assert restored.warehouse_inventory_moment == moment


def test_portion_sales_event_roundtrip() -> None:
    tech = TechnicianId("t1")
    inv = "inv-abc"
    moment = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    event = SettlementPortionSalesVerifyRequested(
        event_id=EventId(f"portion:{tech.value}:{inv}:sales"),
        technician_id=tech,
        warehouse_inventory_id=inv,
        warehouse_inventory_moment=moment,
        occurred_at=moment,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert isinstance(restored, SettlementPortionSalesVerifyRequested)
    assert restored.event_id.value.endswith(":sales")


def test_portion_reconcile_event_roundtrip_with_not_before() -> None:
    # happy: reconcile event with not_before set — roundtrip preserves it
    tech = TechnicianId("t1")
    inv = "inv-abc"
    moment = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    not_before = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    event = SettlementPortionReconcileRequested(
        event_id=EventId(f"portion:{tech.value}:{inv}:reconcile"),
        technician_id=tech,
        warehouse_inventory_id=inv,
        warehouse_inventory_moment=moment,
        occurred_at=moment,
        not_before=not_before,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert isinstance(restored, SettlementPortionReconcileRequested)
    assert restored.not_before == not_before


def test_portion_reconcile_event_roundtrip_without_not_before() -> None:
    # edge / regression: not_before=None (default) — roundtrip preserves None
    tech = TechnicianId("t1")
    inv = "inv-abc"
    moment = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    event = SettlementPortionReconcileRequested(
        event_id=EventId(f"portion:{tech.value}:{inv}:reconcile"),
        technician_id=tech,
        warehouse_inventory_id=inv,
        warehouse_inventory_moment=moment,
        occurred_at=moment,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert isinstance(restored, SettlementPortionReconcileRequested)
    assert restored.not_before is None


def test_portion_sync_event_roundtrip_has_no_not_before_attribute_leak() -> None:
    # regression: non-reconcile portion events unaffected by the new payload key
    tech = TechnicianId("t1")
    inv = "inv-abc"
    moment = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    event = SettlementPortionSyncTransfersRequested(
        event_id=EventId(f"portion:{tech.value}:{inv}:sync"),
        technician_id=tech,
        warehouse_inventory_id=inv,
        warehouse_inventory_moment=moment,
        occurred_at=moment,
    )
    doc = event_to_outbox_document(event)
    assert "not_before" not in doc["payload"]
