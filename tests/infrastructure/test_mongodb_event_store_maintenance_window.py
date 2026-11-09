from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import mongomock
import pytest

from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import MaintenanceCompleted, PhotosSubmitted
from src.infrastructure.mongodb import MongoEventStore

_INDEX_NAME = "maintenance_completed_window"
_COMPOSITE_INDEX_NAME = "photos_maintenance_completed_window"
_MACHINE = MachineId("101")
_TECH = TechnicianId("001")
_START = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
_END = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)


@pytest.fixture
def mongo_event_store() -> MongoEventStore:
    client = mongomock.MongoClient()
    collection = client["test_db"]["machine_events"]
    return MongoEventStore.from_collection(collection)


def test_mongo_event_store_ensures_maintenance_completed_index(
    mongo_event_store: MongoEventStore,
) -> None:
    collection = mongo_event_store._collection  # noqa: SLF001 — test introspection
    indexes = collection.index_information()
    assert _INDEX_NAME in indexes
    assert _COMPOSITE_INDEX_NAME in indexes


def test_mongo_event_store_lists_maintenance_in_window_without_full_scan(
    mongo_event_store: MongoEventStore,
) -> None:
    early = MaintenanceCompleted(
        event_id=EventId("mnt-early"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 12, 2, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 12, 2, 0, tzinfo=UTC),
    )
    late = MaintenanceCompleted(
        event_id=EventId("mnt-late"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )
    mongo_event_store.append(late, expected_version=0)
    mongo_event_store.append(early, expected_version=1)

    with patch.object(MongoEventStore, "get_events_for_machine", autospec=True) as full_scan:
        got = mongo_event_store.list_maintenance_completed_in_completed_at_window(
            _MACHINE,
            completed_at_start_inclusive=_START,
            completed_at_end_exclusive=_END,
        )
        full_scan.assert_not_called()

    assert [event.event_id for event in got] == [EventId("mnt-early"), EventId("mnt-late")]


def test_maintenance_window_includes_composite_photo_fact_once(
    mongo_event_store: MongoEventStore,
) -> None:
    photo = PhotosSubmitted(
        event_id=EventId("photo-composite"),
        batch_id=BatchId("batch-1"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=2,
        submitted_at=_COMPLETED_AT,
        occurred_at=_COMPLETED_AT,
        maintenance_completed_at=_COMPLETED_AT,
    )
    mongo_event_store.append(photo, expected_version=0)

    got = mongo_event_store.list_maintenance_completed_in_completed_at_window(
        _MACHINE,
        completed_at_start_inclusive=_START,
        completed_at_end_exclusive=_END,
    )

    assert len(got) == 1
    assert isinstance(got[0], MaintenanceCompleted)
    assert got[0].event_id == EventId("photo-composite")
    assert got[0].completed_at == _COMPLETED_AT
    assert got[0].technician_id == _TECH
    assert got[0].machine_id == _MACHINE


def test_maintenance_window_does_not_count_photo_without_embedded_fact(
    mongo_event_store: MongoEventStore,
) -> None:
    photo = PhotosSubmitted(
        event_id=EventId("photo-no-fact"),
        batch_id=BatchId("batch-2"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=2,
        submitted_at=_COMPLETED_AT,
        occurred_at=_COMPLETED_AT,
        maintenance_completed_at=None,
    )
    mongo_event_store.append(photo, expected_version=0)

    got = mongo_event_store.list_maintenance_completed_in_completed_at_window(
        _MACHINE,
        completed_at_start_inclusive=_START,
        completed_at_end_exclusive=_END,
    )

    assert got == ()
