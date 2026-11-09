from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    RevisionCompleted,
)
from src.domain.models import RevisionSource
from src.infrastructure.machine_revision_history import EventStoreMachineRevisionHistoryReader
from src.infrastructure.memory import InMemoryEventStore

_MACHINE_ID = MachineId("vm-01")
_OPENED = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
_INSIDE = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def test_list_revisions_filters_revision_completed_sorted_by_completed_at() -> None:
    store = InMemoryEventStore()
    rev1 = RevisionCompleted(
        event_id=EventId("evt-rev-1"),
        revision_id=RevisionId("rev-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=_MACHINE_ID,
        completed_at=_OPENED,
        occurred_at=_OPENED,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-rev",
        form_token="token-rev-1",
    )
    loading = LoadingSubmitted(
        event_id=EventId("evt-load-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=_MACHINE_ID,
        submitted_at=_INSIDE,
        occurred_at=_INSIDE,
        form_id="form-load",
        form_token="token-load-1",
    )
    rev2 = RevisionCompleted(
        event_id=EventId("evt-rev-2"),
        revision_id=RevisionId("rev-2"),
        technician_id=TechnicianId("tech-b"),
        machine_id=_MACHINE_ID,
        completed_at=_CLOSED,
        occurred_at=_CLOSED,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-rev",
        form_token="token-rev-2",
    )
    store.append(rev1, expected_version=0)
    store.append(loading, expected_version=1)
    store.append(rev2, expected_version=2)

    reader = EventStoreMachineRevisionHistoryReader(event_store=store)
    revisions = reader.list_revisions(_MACHINE_ID)

    assert len(revisions) == 2
    assert revisions[0].revision_id.value == "rev-1"
    assert revisions[1].revision_id.value == "rev-2"
    assert len(reader.list_loadings(_MACHINE_ID)) == 1


def test_list_loadings_sorted_by_occurred_at() -> None:
    store = InMemoryEventStore()
    early = LoadingSubmitted(
        event_id=EventId("evt-load-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=_MACHINE_ID,
        submitted_at=_INSIDE,
        occurred_at=_INSIDE,
        form_id="form-load",
        form_token="token-load-1",
    )
    late = LoadingSubmitted(
        event_id=EventId("evt-load-2"),
        technician_id=TechnicianId("tech-a"),
        machine_id=_MACHINE_ID,
        submitted_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        form_id="form-load",
        form_token="token-load-2",
    )
    store.append(late, expected_version=0)
    store.append(early, expected_version=1)

    reader = EventStoreMachineRevisionHistoryReader(event_store=store)
    loadings = reader.list_loadings(_MACHINE_ID)

    assert len(loadings) == 2
    assert loadings[0].event_id.value == "evt-load-1"
    assert loadings[1].event_id.value == "evt-load-2"


def test_list_loadings_only_loading_submitted() -> None:
    store = InMemoryEventStore()
    store.append(
        LoadingSubmitted(
            event_id=EventId("evt-migrated-pre"),
            technician_id=TechnicianId("tech-a"),
            machine_id=_MACHINE_ID,
            submitted_at=_INSIDE,
            occurred_at=_INSIDE,
            form_id="form-pre",
            form_token="token-pre-1",
        ),
        expected_version=0,
    )
    loadings = EventStoreMachineRevisionHistoryReader(event_store=store).list_loadings(_MACHINE_ID)
    assert [item.event_id.value for item in loadings] == ["evt-migrated-pre"]
    assert all(isinstance(item, LoadingSubmitted) for item in loadings)
