from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import BatchId, EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import (
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
)
from src.domain.models import RevisionSource
from src.infrastructure.memory import InMemoryEventStore

_MACHINE = MachineId("101")
_TECH = TechnicianId("001")
_START = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
_END = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)


def test_in_memory_event_store_lists_maintenance_in_window_sorted() -> None:
    store = InMemoryEventStore()
    late = MaintenanceCompleted(
        event_id=EventId("mnt-late"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )
    early = MaintenanceCompleted(
        event_id=EventId("mnt-early"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 12, 2, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 12, 2, 0, tzinfo=UTC),
    )
    outside = MaintenanceCompleted(
        event_id=EventId("mnt-out"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 13, 2, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 13, 2, 0, tzinfo=UTC),
    )
    revision = RevisionCompleted(
        event_id=EventId("rev-1"),
        revision_id=RevisionId("r1"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 12, 3, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 12, 3, 0, tzinfo=UTC),
        source=RevisionSource.GOOGLE_FORM,
        form_id="f",
        form_token="t",
    )

    store.append(late, expected_version=0)
    store.append(early, expected_version=1)
    store.append(outside, expected_version=2)
    store.append(revision, expected_version=3)

    got = store.list_maintenance_completed_in_completed_at_window(
        _MACHINE,
        completed_at_start_inclusive=_START,
        completed_at_end_exclusive=_END,
    )

    assert [event.event_id for event in got] == [EventId("mnt-early"), EventId("mnt-late")]


def test_maintenance_window_includes_composite_photo_fact_once() -> None:
    store = InMemoryEventStore()
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
    store.append(photo, expected_version=0)

    got = store.list_maintenance_completed_in_completed_at_window(
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


def test_maintenance_window_does_not_count_photo_without_embedded_fact() -> None:
    store = InMemoryEventStore()
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
    store.append(photo, expected_version=0)

    got = store.list_maintenance_completed_in_completed_at_window(
        _MACHINE,
        completed_at_start_inclusive=_START,
        completed_at_end_exclusive=_END,
    )

    assert got == ()
