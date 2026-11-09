from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.application.technician_warehouse.ports import LoadingSubmittedRef
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
)
from src.domain.technician_warehouse.models import TechnicianWarehouseLine
from src.infrastructure.mongodb.serialization import document_from_event
from src.infrastructure.mongodb.technician_warehouse_serialization import (
    warehouse_event_to_document,
)
from src.infrastructure.mongodb.warehouse_loading_backfill_source import (
    MongoWarehouseLoadingBackfillSource,
)

_TECH = TechnicianId("tech-1")
_TECH_B = TechnicianId("tech-2")
_MACHINE = MachineId("vm-01")
_T0 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
_T2 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _source() -> tuple[MongoWarehouseLoadingBackfillSource, object, object]:
    client = mongomock.MongoClient()
    machine_events = client["db"]["machine_events"]
    warehouse_events = client["db"]["technician_warehouse_events"]
    adapter = MongoWarehouseLoadingBackfillSource(
        machine_events=machine_events,
        warehouse_events=warehouse_events,
    )
    return adapter, machine_events, warehouse_events


def test_mongo_backfill_source_lists_submitted_and_observed_ids() -> None:
    adapter, machine_events, warehouse_events = _source()

    loading_a = LoadingSubmitted(
        event_id=EventId("evt-a"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_T1,
        occurred_at=_T1,
        form_id="form",
        form_token="tok-a",
    )
    loading_b = LoadingSubmitted(
        event_id=EventId("evt-b"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_T0,
        occurred_at=_T0,
        form_id="form",
        form_token="tok-b",
    )
    loading_other = LoadingSubmitted(
        event_id=EventId("evt-other"),
        technician_id=_TECH_B,
        machine_id=MachineId("vm-02"),
        submitted_at=_T2,
        occurred_at=_T2,
        form_id="form",
        form_token="tok-o",
    )
    machine_events.insert_one(document_from_event(loading_a, aggregate_version=1))
    machine_events.insert_one(document_from_event(loading_b, aggregate_version=2))
    machine_events.insert_one(document_from_event(loading_other, aggregate_version=1))

    observed = TechnicianWarehouseLoadingObserved(
        event_id=EventId("obs-1"),
        technician_id=_TECH,
        occurred_at=_T1,
        source_event_id="evt-b",
        machine_id=_MACHINE,
        submitted_at=_T0,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("1000")),),
    )
    warehouse_events.insert_one(
        warehouse_event_to_document(observed, aggregate_version=1),
    )

    submitted_all = adapter.list_loading_submitted(technician_id=None)
    assert [item.event_id for item in submitted_all] == ["evt-b", "evt-a", "evt-other"]

    submitted_tech = adapter.list_loading_submitted(technician_id=_TECH)
    assert submitted_tech == (
        LoadingSubmittedRef(
            event_id="evt-b",
            technician_id=_TECH,
            machine_id=_MACHINE,
            submitted_at=_T0,
        ),
        LoadingSubmittedRef(
            event_id="evt-a",
            technician_id=_TECH,
            machine_id=_MACHINE,
            submitted_at=_T1,
        ),
    )

    assert adapter.list_observed_source_event_ids(technician_id=_TECH) == frozenset({"evt-b"})
    assert adapter.list_observed_source_event_ids(technician_id=_TECH_B) == frozenset()
    assert adapter.list_observed_source_event_ids(technician_id=None) == frozenset({"evt-b"})


def test_mongo_backfill_source_lists_only_loading_submitted_type() -> None:
    adapter, machine_events, _warehouse_events = _source()
    loading = LoadingSubmitted(
        event_id=EventId("evt-load"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_T0,
        occurred_at=_T0,
        form_id="form",
        form_token="tok-load",
    )
    machine_events.insert_one(document_from_event(loading, aggregate_version=1))
    # Residual PreLoading type in Mongo (pre-migrate / backup): not listed after cut.
    machine_events.insert_one(
        {
            "event_id": "evt-pre-residual",
            "event_type": "PreLoadingSubmitted",
            "aggregate_id": _MACHINE.value,
            "aggregate_type": "MachineOperations",
            "aggregate_version": 2,
            "occurred_at": _T1,
            "payload": {
                "technician_id": _TECH.value,
                "machine_id": _MACHINE.value,
                "submitted_at": _T1,
                "form_id": "form",
                "form_token": "tok-pre",
            },
            "metadata": {},
        }
    )
    submitted = adapter.list_loading_submitted(technician_id=_TECH)
    assert [item.event_id for item in submitted] == ["evt-load"]


def test_mongo_backfill_source_ignores_other_event_types_and_aggregate_types() -> None:
    adapter, machine_events, warehouse_events = _source()

    loading = LoadingSubmitted(
        event_id=EventId("evt-loading"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_T0,
        occurred_at=_T0,
        form_id="form",
        form_token="tok-loading",
    )
    machine_events.insert_one(document_from_event(loading, aggregate_version=1))
    machine_events.insert_one(
        {
            "event_id": "evt-pre",
            "event_type": "PreLoadingSubmitted",
            "aggregate_id": _MACHINE.value,
            "aggregate_type": "MachineOperations",
            "aggregate_version": 2,
            "occurred_at": _T0,
            "payload": {
                "technician_id": _TECH.value,
                "machine_id": _MACHINE.value,
                "submitted_at": _T0,
                "form_id": "form",
                "form_token": "tok-pre",
            },
            "metadata": {},
        }
    )
    wrong_aggregate = document_from_event(
        LoadingSubmitted(
            event_id=EventId("evt-wrong-agg"),
            technician_id=_TECH,
            machine_id=_MACHINE,
            submitted_at=_T1,
            occurred_at=_T1,
            form_id="form",
            form_token="tok-wrong",
        ),
        aggregate_version=3,
    )
    wrong_aggregate["aggregate_type"] = "NotMachineOperations"
    machine_events.insert_one(wrong_aggregate)

    observed = TechnicianWarehouseLoadingObserved(
        event_id=EventId("obs-1"),
        technician_id=_TECH,
        occurred_at=_T0,
        source_event_id="evt-loading",
        machine_id=_MACHINE,
        submitted_at=_T0,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("1000")),),
    )
    inventory = TechnicianWarehouseInventoryCounted(
        event_id=EventId("inv-1"),
        technician_id=_TECH,
        occurred_at=_T0,
        inventory_id="inv-1",
        form_token="tok-inv",
        counted_at=_T0,
        lines=(("coffee", Decimal("1")),),
        baseline=True,
    )
    warehouse_events.insert_one(warehouse_event_to_document(observed, aggregate_version=1))
    warehouse_events.insert_one(warehouse_event_to_document(inventory, aggregate_version=2))
    wrong_observed = warehouse_event_to_document(
        TechnicianWarehouseLoadingObserved(
            event_id=EventId("obs-wrong"),
            technician_id=_TECH,
            occurred_at=_T1,
            source_event_id="evt-should-ignore",
            machine_id=_MACHINE,
            submitted_at=_T1,
            lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("1")),),
        ),
        aggregate_version=3,
    )
    wrong_observed["aggregate_type"] = "NotTechnicianWarehouse"
    warehouse_events.insert_one(wrong_observed)

    assert [item.event_id for item in adapter.list_loading_submitted(technician_id=None)] == [
        "evt-loading",
    ]
    assert adapter.list_observed_source_event_ids(technician_id=None) == frozenset({"evt-loading"})
