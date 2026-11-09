from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
)
from src.domain.technician_warehouse.models import TechnicianWarehouseLine
from src.infrastructure.mongodb.technician_warehouse_serialization import (
    TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
)
from src.infrastructure.outbox.serialization import (
    event_from_outbox_document,
    event_to_outbox_document,
)

_TECH = TechnicianId("tech-codec-1")
_NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _inventory() -> TechnicianWarehouseInventoryCounted:
    return TechnicianWarehouseInventoryCounted(
        event_id=EventId("evt-inv-codec-1"),
        technician_id=_TECH,
        occurred_at=_NOW,
        inventory_id="inv-codec-1",
        form_token="token-codec-1",
        counted_at=_NOW,
        lines=(("coffee", Decimal("3")),),
        baseline=True,
    )


def test_outbox_inventory_counted_round_trip() -> None:
    event = _inventory()
    document = event_to_outbox_document(event)
    assert document["aggregate_type"] == TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE
    assert document["aggregate_id"] == _TECH.value
    assert document["event_type"] == "TechnicianWarehouseInventoryCounted"
    restored = event_from_outbox_document(document)
    assert isinstance(restored, TechnicianWarehouseInventoryCounted)
    assert restored.event_id == event.event_id
    assert restored.technician_id == event.technician_id
    assert restored.inventory_id == event.inventory_id
    assert restored.form_token == event.form_token
    assert restored.lines == event.lines
    assert restored.baseline is True


def test_outbox_rejects_non_inventory_warehouse_event() -> None:
    loading = TechnicianWarehouseLoadingObserved(
        event_id=EventId("evt-load-codec-1"),
        technician_id=_TECH,
        occurred_at=_NOW,
        source_event_id="loading-1",
        machine_id=MachineId("vm-01"),
        submitted_at=_NOW,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("1")),),
    )
    with pytest.raises((TypeError, ValueError)):
        event_to_outbox_document(loading)


def test_outbox_rejects_warehouse_document_that_is_not_inventory() -> None:
    document = {
        "event_id": "evt-xfer-1",
        "event_type": "TechnicianWarehouseTransferVoided",
        "aggregate_id": _TECH.value,
        "aggregate_type": TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
        "aggregate_version": 0,
        "occurred_at": _NOW,
        "payload": {
            "external_document_id": "move-1",
            "previous_content_hash": "hash-1",
            "observed_at": _NOW,
        },
    }
    with pytest.raises((TypeError, ValueError)):
        event_from_outbox_document(document)
