from __future__ import annotations

from datetime import UTC, datetime

from src.application.sales_monitoring.last_maintenance import (
    EventStoreLastMaintenanceByMachine,
    LastMaintenanceSnapshot,
)
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import MaintenanceCompleted, PhotosSubmitted
from src.infrastructure.memory import InMemoryEventStore

_MACHINE_ID = MachineId("vm-lm-01")
_OTHER_MACHINE = MachineId("vm-lm-other")
_TECH_A = TechnicianId("tech-a")
_TECH_B = TechnicianId("tech-b")
_EARLIER = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
_LATER = datetime(2026, 7, 20, 14, 30, tzinfo=UTC)


def _maintenance(
    *,
    event_id: str,
    technician_id: TechnicianId,
    machine_id: MachineId,
    completed_at: datetime,
) -> MaintenanceCompleted:
    return MaintenanceCompleted(
        event_id=EventId(event_id),
        technician_id=technician_id,
        machine_id=machine_id,
        completed_at=completed_at,
        occurred_at=completed_at,
    )


def _append(store: InMemoryEventStore, event: MaintenanceCompleted | PhotosSubmitted) -> None:
    store.append(
        event,
        expected_version=len(store.get_events_for_machine(event.machine_id)),
    )


def test_last_maintenance_returns_latest_completed() -> None:
    store = InMemoryEventStore()
    _append(
        store,
        _maintenance(
            event_id="evt-lm-1",
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=_EARLIER,
        ),
    )
    _append(
        store,
        _maintenance(
            event_id="evt-lm-2",
            technician_id=_TECH_B,
            machine_id=_MACHINE_ID,
            completed_at=_LATER,
        ),
    )
    _append(
        store,
        _maintenance(
            event_id="evt-lm-other",
            technician_id=_TECH_A,
            machine_id=_OTHER_MACHINE,
            completed_at=_LATER,
        ),
    )
    _append(
        store,
        PhotosSubmitted(
            event_id=EventId("evt-lm-photos"),
            batch_id=BatchId("batch-1"),
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            photo_count=1,
            submitted_at=_LATER,
            occurred_at=_LATER,
        ),
    )

    reader = EventStoreLastMaintenanceByMachine(event_store=store)

    snapshot = reader.get(_MACHINE_ID)

    assert snapshot == LastMaintenanceSnapshot(
        technician_id=_TECH_B,
        completed_at=_LATER,
    )


def test_last_maintenance_none_when_no_events() -> None:
    reader = EventStoreLastMaintenanceByMachine(event_store=InMemoryEventStore())

    assert reader.get(_MACHINE_ID) is None


def test_last_maintenance_reads_composite_photo_embedded_fact() -> None:
    store = InMemoryEventStore()
    _append(
        store,
        _maintenance(
            event_id="evt-lm-legacy",
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=_EARLIER,
        ),
    )
    _append(
        store,
        PhotosSubmitted(
            event_id=EventId("evt-lm-photo-fact"),
            batch_id=BatchId("batch-fact"),
            technician_id=_TECH_B,
            machine_id=_MACHINE_ID,
            photo_count=2,
            submitted_at=_LATER,
            occurred_at=_LATER,
            maintenance_completed_at=_LATER,
        ),
    )
    reader = EventStoreLastMaintenanceByMachine(event_store=store)

    assert reader.get(_MACHINE_ID) == LastMaintenanceSnapshot(
        technician_id=_TECH_B,
        completed_at=_LATER,
    )


def test_last_maintenance_ignores_photo_without_embedded_fact() -> None:
    store = InMemoryEventStore()
    _append(
        store,
        _maintenance(
            event_id="evt-lm-keep",
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=_EARLIER,
        ),
    )
    _append(
        store,
        PhotosSubmitted(
            event_id=EventId("evt-lm-photo-none"),
            batch_id=BatchId("batch-none"),
            technician_id=_TECH_B,
            machine_id=_MACHINE_ID,
            photo_count=2,
            submitted_at=_LATER,
            occurred_at=_LATER,
            maintenance_completed_at=None,
        ),
    )
    reader = EventStoreLastMaintenanceByMachine(event_store=store)

    assert reader.get(_MACHINE_ID) == LastMaintenanceSnapshot(
        technician_id=_TECH_A,
        completed_at=_EARLIER,
    )
