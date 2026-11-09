from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock
import pytest

from src.application.technician_warehouse.errors import TechnicianWarehouseConcurrencyError
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseEvent,
    TechnicianWarehouseExitClosed,
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferFinalized,
    TechnicianWarehouseTransferObserved,
    TechnicianWarehouseTransferVoided,
)
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection
from src.infrastructure.mongodb.technician_warehouse import (
    MongoTechnicianWarehouseEventStore,
    MongoTechnicianWarehouseRepository,
)
from src.infrastructure.mongodb.technician_warehouse_serialization import (
    TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
    warehouse_event_from_document,
    warehouse_event_to_document,
)

_TECHNICIAN_ID = TechnicianId("tech-1")
_NOW = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


def _store() -> MongoTechnicianWarehouseEventStore:
    collection = mongomock.MongoClient().db.technician_warehouse_events
    return MongoTechnicianWarehouseEventStore.from_collection(collection)


def _repository() -> MongoTechnicianWarehouseRepository:
    return MongoTechnicianWarehouseRepository(event_store=_store())


def _transfer_observed() -> TechnicianWarehouseTransferObserved:
    return TechnicianWarehouseTransferObserved(
        event_id=EventId("evt-transfer-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        external_document_id="move-1",
        moment=_NOW,
        updated_at=_NOW,
        observed_at=_NOW,
        content_hash="hash-1",
        direction=TransferDirection.SUPPLY_IN,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("10")),),
    )


def _transfer_voided() -> TechnicianWarehouseTransferVoided:
    return TechnicianWarehouseTransferVoided(
        event_id=EventId("evt-void-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        external_document_id="move-1",
        previous_content_hash="hash-1",
        observed_at=_NOW,
    )


def _loading_observed() -> TechnicianWarehouseLoadingObserved:
    return TechnicianWarehouseLoadingObserved(
        event_id=EventId("evt-loading-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        source_event_id="loading-1",
        machine_id=MachineId("vm-01"),
        submitted_at=_NOW,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("5")),),
    )


def _baseline_inventory() -> TechnicianWarehouseInventoryCounted:
    return TechnicianWarehouseInventoryCounted(
        event_id=EventId("evt-inv-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=_NOW,
        lines=(("coffee", Decimal("10")),),
        baseline=True,
    )


def _transfer_finalized() -> TechnicianWarehouseTransferFinalized:
    return TechnicianWarehouseTransferFinalized(
        event_id=EventId("evt-finalized-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        session_id="session-1",
        external_document_ids=("move-1",),
        finalized_at=_NOW,
    )


@pytest.mark.parametrize(
    "event",
    [
        _transfer_observed(),
        _transfer_voided(),
        _loading_observed(),
        _baseline_inventory(),
        _transfer_finalized(),
    ],
)
def test_warehouse_event_bson_round_trip(event: TechnicianWarehouseEvent) -> None:
    document = warehouse_event_to_document(event, aggregate_version=3)
    assert document["aggregate_type"] == TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE
    assert document["aggregate_id"] == _TECHNICIAN_ID.value
    assert document["aggregate_version"] == 3
    assert warehouse_event_from_document(document) == event


def test_warehouse_event_from_document_rejects_unknown_type() -> None:
    document = warehouse_event_to_document(_baseline_inventory(), aggregate_version=1)
    document["event_type"] = "Broken"
    with pytest.raises(ValueError, match="Unknown technician warehouse event type: Broken"):
        warehouse_event_from_document(document)


def test_exit_closed_event_mongo_round_trip() -> None:
    event = TechnicianWarehouseExitClosed(
        event_id=EventId("evt-exit-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        closed_at=_NOW,
        return_external_document_id="move-ret",
        return_content_hash="hash-ret",
    )
    document = warehouse_event_to_document(event, aggregate_version=4)
    assert document["event_type"] == "TechnicianWarehouseExitClosed"
    assert document["payload"]["return_external_document_id"] == "move-ret"
    assert document["payload"]["return_content_hash"] == "hash-ret"
    restored = warehouse_event_from_document(document)
    assert restored == event


def test_mongo_repository_append_and_rehydrate() -> None:
    repository = _repository()
    warehouse = repository.get(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=_NOW,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    repository.save(warehouse, expected_version=0)
    assert repository.get(_TECHNICIAN_ID).latest_inventory_id == "inv-1"


def test_mongo_store_duplicate_event_id_is_idempotent() -> None:
    store = _store()
    event = _baseline_inventory()
    store.append(_TECHNICIAN_ID, 0, (event,))
    store.append(_TECHNICIAN_ID, 0, (event,))
    assert store.get_events_for_technician(_TECHNICIAN_ID) == [event]


def test_mongo_store_rejects_stale_expected_version() -> None:
    store = _store()
    store.append(_TECHNICIAN_ID, 0, (_baseline_inventory(),))
    with pytest.raises(TechnicianWarehouseConcurrencyError):
        store.append(_TECHNICIAN_ID, 0, (_loading_observed(),))
