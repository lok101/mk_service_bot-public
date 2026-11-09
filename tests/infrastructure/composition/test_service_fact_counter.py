from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import MaintenanceCompleted, PhotosSubmitted
from src.infrastructure.composition.adapters.service_fact_counter import (
    EventStoreServiceFactCounter,
)
from src.infrastructure.memory import InMemoryEventStore

_MACHINE_ID = MachineId("101")
_OTHER_MACHINE = MachineId("102")
_TECH = TechnicianId("tech-1")
_OPENED = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)


def _maintenance(
    *, event_id: str, machine_id: MachineId, completed_at: datetime
) -> MaintenanceCompleted:
    return MaintenanceCompleted(
        event_id=EventId(event_id),
        technician_id=_TECH,
        machine_id=machine_id,
        completed_at=completed_at,
        occurred_at=completed_at,
    )


def _append(store: InMemoryEventStore, event: MaintenanceCompleted | PhotosSubmitted) -> None:
    store.append(
        event,
        expected_version=len(store.get_events_for_machine(event.machine_id)),
    )


def test_service_fact_counter_half_open_window() -> None:
    store = InMemoryEventStore()
    _append(
        store,
        _maintenance(
            event_id="evt-at-open",
            machine_id=_MACHINE_ID,
            completed_at=_OPENED,
        ),
    )
    _append(
        store,
        _maintenance(
            event_id="evt-inside",
            machine_id=_MACHINE_ID,
            completed_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
        ),
    )
    _append(
        store,
        _maintenance(
            event_id="evt-at-close",
            machine_id=_MACHINE_ID,
            completed_at=_CLOSED,
        ),
    )
    _append(
        store,
        _maintenance(
            event_id="evt-after-close",
            machine_id=_MACHINE_ID,
            completed_at=datetime(2026, 5, 10, 12, 0, 1, tzinfo=UTC),
        ),
    )
    _append(
        store,
        _maintenance(
            event_id="evt-other-machine",
            machine_id=_OTHER_MACHINE,
            completed_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
        ),
    )
    counter = EventStoreServiceFactCounter(store)

    assert (
        counter.count_completed(
            _MACHINE_ID,
            opened_at=_OPENED,
            closed_at=_CLOSED,
        )
        == 2
    )


def test_service_fact_counter_counts_legacy_and_composite_photo_once() -> None:
    store = InMemoryEventStore()
    _append(
        store,
        _maintenance(
            event_id="evt-legacy",
            machine_id=_MACHINE_ID,
            completed_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
        ),
    )
    _append(
        store,
        PhotosSubmitted(
            event_id=EventId("evt-photo-fact"),
            batch_id=BatchId("batch-1"),
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            photo_count=2,
            submitted_at=datetime(2026, 5, 6, 11, 0, tzinfo=UTC),
            occurred_at=datetime(2026, 5, 6, 11, 0, tzinfo=UTC),
            maintenance_completed_at=datetime(2026, 5, 6, 11, 0, tzinfo=UTC),
        ),
    )
    counter = EventStoreServiceFactCounter(store)

    assert (
        counter.count_completed(
            _MACHINE_ID,
            opened_at=_OPENED,
            closed_at=_CLOSED,
        )
        == 2
    )


def test_service_fact_counter_ignores_photo_without_embedded_fact() -> None:
    store = InMemoryEventStore()
    _append(
        store,
        PhotosSubmitted(
            event_id=EventId("evt-photo-none"),
            batch_id=BatchId("batch-2"),
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            photo_count=2,
            submitted_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
            occurred_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
            maintenance_completed_at=None,
        ),
    )
    counter = EventStoreServiceFactCounter(store)

    assert (
        counter.count_completed(
            _MACHINE_ID,
            opened_at=_OPENED,
            closed_at=_CLOSED,
        )
        == 0
    )
