from __future__ import annotations

from datetime import UTC, datetime

from beartype import beartype

from src.application.machine_operations.ports import EventStore
from src.domain.ids import EventId, MachineId, RevisionId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.mongodb import MongoEventStore
from src.infrastructure.testing.stubs import OTHER_TECHNICIAN_ID, TEST_TECHNICIAN_ID


@beartype
def build_test_revision_completed_events() -> list[RevisionCompleted]:
    events: list[RevisionCompleted] = [
        RevisionCompleted(
            event_id=EventId("event-rev-vm-01"),
            revision_id=RevisionId("rev-vm-01"),
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=MachineId("vm-01"),
            completed_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
            occurred_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
            source=RevisionSource.GOOGLE_FORM,
            form_id="seed-form-revision",
            form_token="seed-token-vm-01",
        ),
    ]
    for index in range(2, 26):
        machine_id = MachineId(f"vm-{index:02d}")
        completed_at = datetime(2026, 5, 15, 9, index, tzinfo=UTC)
        events.append(
            RevisionCompleted(
                event_id=EventId(f"event-rev-{machine_id.value}"),
                revision_id=RevisionId(f"rev-{machine_id.value}"),
                technician_id=OTHER_TECHNICIAN_ID,
                machine_id=machine_id,
                completed_at=completed_at,
                occurred_at=completed_at,
                source=RevisionSource.GOOGLE_FORM,
                form_id="seed-form-revision",
                form_token=f"seed-token-{machine_id.value}",
            ),
        )

    return events


@beartype
def seed_test_machine_revision_events(event_store: EventStore) -> None:
    if isinstance(event_store, MongoEventStore) and event_store.has_any_events():
        return
    for event in build_test_revision_completed_events():
        event_store.append(
            event,
            expected_version=len(event_store.get_events_for_machine(event.machine_id)),
        )
