from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

import mongomock
import pytest

from src.application.machine_operations.errors import MachineOperationsConcurrencyError
from src.domain.ids import BatchId, EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations import (
    CompleteRevision,
    LoadingSubmitted,
    RevisionCompleted,
    SubmitLoading,
)
from src.domain.machine_operations.events import (
    PhotosSubmitted,
)
from src.domain.machine_operations.events import (
    RevisionCompleted as RevisionCompletedEvent,
)
from src.domain.models import PrefilledFormLink, RevisionSource
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore
from src.infrastructure.mongodb import MongoEventStore
from src.infrastructure.mongodb.errors import EventStoreConcurrencyError
from src.infrastructure.mongodb.serialization import (
    document_from_event,
    event_from_bson,
    event_to_document,
)


class _VersionedEventStore(Protocol):
    def append(self, event: object, *, expected_version: int) -> None: ...

    def get_events_for_machine(self, machine_id: MachineId) -> list[object]: ...


@pytest.fixture
def mongo_event_store() -> MongoEventStore:
    client = mongomock.MongoClient()
    collection = client["test_db"]["machine_events"]
    return MongoEventStore.from_collection(collection)


_DEFAULT_MACHINE = MachineId("vm-01")


def _revision(
    *,
    event_id: str,
    machine_id: MachineId = _DEFAULT_MACHINE,
) -> RevisionCompletedEvent:
    return RevisionCompletedEvent(
        event_id=EventId(event_id),
        revision_id=RevisionId(f"rev-{event_id}"),
        technician_id=TechnicianId("tech-a"),
        machine_id=machine_id,
        completed_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token=f"token-{event_id}",
    )


def _store_for_kind(
    store_kind: str,
    mongo_event_store: MongoEventStore,
) -> _VersionedEventStore:
    return InMemoryEventStore() if store_kind == "memory" else mongo_event_store


def _raw_versions(store: MongoEventStore, machine_id: MachineId) -> list[int]:
    cursor = store._collection.find(
        {"aggregate_id": machine_id.value},
        sort=[("aggregate_version", 1)],
    )
    return [int(document["aggregate_version"]) for document in cursor]


@pytest.mark.parametrize("store_kind", ["memory", "mongo"])
def test_append_writes_exact_expected_version_plus_one(
    store_kind: str,
    mongo_event_store: MongoEventStore,
) -> None:
    store = _store_for_kind(store_kind, mongo_event_store)
    machine_id = MachineId("vm-01")
    event = _revision(event_id="evt-1", machine_id=machine_id)

    store.append(event, expected_version=0)

    assert store.get_events_for_machine(machine_id) == [event]
    if store_kind == "mongo":
        assert _raw_versions(mongo_event_store, machine_id) == [1]


@pytest.mark.parametrize("store_kind", ["memory", "mongo"])
def test_append_rejects_occupied_expected_version_with_other_event_id(
    store_kind: str,
    mongo_event_store: MongoEventStore,
) -> None:
    store = _store_for_kind(store_kind, mongo_event_store)
    machine_id = MachineId("vm-01")
    first = _revision(event_id="evt-winner", machine_id=machine_id)
    loser = _revision(event_id="evt-loser", machine_id=machine_id)
    store.append(first, expected_version=0)

    with pytest.raises(EventStoreConcurrencyError):
        store.append(loser, expected_version=0)

    assert store.get_events_for_machine(machine_id) == [first]
    if store_kind == "mongo":
        assert _raw_versions(mongo_event_store, machine_id) == [1]


@pytest.mark.parametrize("store_kind", ["memory", "mongo"])
def test_append_same_event_id_is_idempotent_even_with_stale_expected_version(
    store_kind: str,
    mongo_event_store: MongoEventStore,
) -> None:
    store = _store_for_kind(store_kind, mongo_event_store)
    machine_id = MachineId("vm-01")
    event = _revision(event_id="evt-dup", machine_id=machine_id)
    store.append(event, expected_version=0)
    store.append(_revision(event_id="evt-other", machine_id=machine_id), expected_version=1)

    store.append(event, expected_version=0)

    assert store.get_events_for_machine(machine_id) == [
        event,
        _revision(event_id="evt-other", machine_id=machine_id),
    ]
    if store_kind == "mongo":
        assert _raw_versions(mongo_event_store, machine_id) == [1, 2]


@pytest.mark.parametrize("store_kind", ["memory", "mongo"])
def test_append_rejects_gap_expected_version(
    store_kind: str,
    mongo_event_store: MongoEventStore,
) -> None:
    store = _store_for_kind(store_kind, mongo_event_store)
    machine_id = MachineId("vm-01")
    store.append(_revision(event_id="evt-1", machine_id=machine_id), expected_version=0)

    with pytest.raises(EventStoreConcurrencyError):
        store.append(_revision(event_id="evt-gap", machine_id=machine_id), expected_version=5)

    assert len(store.get_events_for_machine(machine_id)) == 1


def test_append_and_load_events_for_machine(mongo_event_store: MongoEventStore) -> None:
    machine_id = MachineId("vm-01")
    event = RevisionCompletedEvent(
        event_id=EventId("evt-1"),
        revision_id=RevisionId("rev-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=machine_id,
        completed_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token="token-1",
    )

    mongo_event_store.append(event, expected_version=0)
    loaded = mongo_event_store.get_events_for_machine(machine_id)

    assert loaded == [event]


def test_append_is_idempotent_by_event_id(mongo_event_store: MongoEventStore) -> None:
    machine_id = MachineId("vm-01")
    event = RevisionCompletedEvent(
        event_id=EventId("evt-dup"),
        revision_id=RevisionId("rev-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=machine_id,
        completed_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token="token-1",
    )

    mongo_event_store.append(event, expected_version=0)
    mongo_event_store.append(event, expected_version=0)

    assert len(mongo_event_store.get_events_for_machine(machine_id)) == 1


def test_repository_save_and_reload_with_mongo(
    mongo_event_store: MongoEventStore,
) -> None:
    repository = EventSourcedMachineOperationsRepository(event_store=mongo_event_store)
    machine_id = MachineId("vm-99")
    tech = TechnicianId("tech-a")
    completed_at = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)

    revision_form_link = PrefilledFormLink(url="https://example.com/revision")
    aggregate = repository.get(machine_id)
    assert (
        aggregate.get_service_capabilities(
            tech,
            revision_form_link=revision_form_link,
        ).responsibility_phase
        == "awaiting_handover"
    )

    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=tech,
            submitted_at=completed_at - timedelta(minutes=1),
            form_id="form-loading",
            form_token="load-before-token-rev-1",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)

    aggregate = repository.get(machine_id)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=tech,
            completed_at=completed_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert isinstance(result, RevisionCompleted)
    repository.save(aggregate)

    reloaded = repository.get(machine_id)
    caps = reloaded.get_service_capabilities(
        tech,
        revision_form_link=revision_form_link,
    )
    assert caps.responsibility_phase == "responsible"


class _RaisingAppendEventStore:
    def __init__(self, inner: MongoEventStore) -> None:
        self._inner = inner

    def append(self, event: object, *, expected_version: int) -> None:
        raise EventStoreConcurrencyError("simulated race")

    def get_events_for_machine(self, machine_id: MachineId) -> list[object]:
        return self._inner.get_events_for_machine(machine_id)

    def list_maintenance_completed_in_completed_at_window(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._inner.list_maintenance_completed_in_completed_at_window(*args, **kwargs)


def test_repository_maps_event_store_concurrency_error(
    mongo_event_store: MongoEventStore,
) -> None:
    machine_id = MachineId("vm-race")
    tech = TechnicianId("tech-a")
    completed_at = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    seed_repo = EventSourcedMachineOperationsRepository(event_store=mongo_event_store)
    seed = seed_repo.get(machine_id)
    loading = seed.submit_loading(
        SubmitLoading(
            technician_id=tech,
            submitted_at=completed_at - timedelta(minutes=1),
            form_id="form-loading",
            form_token="load-before-token-race",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    seed_repo.save(seed)

    repository = EventSourcedMachineOperationsRepository(
        event_store=_RaisingAppendEventStore(mongo_event_store),
    )
    aggregate = repository.get(machine_id)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=tech,
            completed_at=completed_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-race",
        ),
    )
    assert isinstance(result, RevisionCompleted)

    with pytest.raises(MachineOperationsConcurrencyError):
        repository.save(aggregate)


def test_photos_submitted_composite_round_trip_preserves_maintenance_fact() -> None:
    completed_at = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
    event = PhotosSubmitted(
        event_id=EventId("evt-photos-composite"),
        batch_id=BatchId("batch-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        photo_count=2,
        submitted_at=completed_at,
        occurred_at=completed_at,
        maintenance_completed_at=completed_at,
    )

    document = event_to_document(event, aggregate_version=5)
    restored = event_from_bson(document_from_event(event, aggregate_version=5))

    assert restored == event
    assert document.payload["maintenance_completed_at"] == completed_at


def test_legacy_photos_document_without_maintenance_field_decodes_as_none() -> None:
    document = {
        "event_id": "evt-photos-legacy",
        "event_type": "PhotosSubmitted",
        "aggregate_id": "vm-01",
        "aggregate_type": "MachineOperations",
        "aggregate_version": 5,
        "occurred_at": datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        "payload": {
            "batch_id": "batch-1",
            "technician_id": "tech-a",
            "machine_id": "vm-01",
            "photo_count": 2,
            "submitted_at": datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
            "purpose": "loading",
        },
        "metadata": {},
    }

    restored = event_from_bson(document)

    assert isinstance(restored, PhotosSubmitted)
    assert restored.maintenance_completed_at is None
