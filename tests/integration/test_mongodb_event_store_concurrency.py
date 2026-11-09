from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import pytest
from pymongo.database import Database

from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.mongodb import MongoEventStore
from src.infrastructure.mongodb.errors import EventStoreConcurrencyError

pytestmark = pytest.mark.integration


def _revision_completed_event(
    *,
    machine_id: MachineId,
    event_id: str,
    form_token: str,
) -> RevisionCompleted:
    completed_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    return RevisionCompleted(
        event_id=EventId(event_id),
        revision_id=RevisionId(f"rev-{event_id}"),
        technician_id=TechnicianId("tech-a"),
        machine_id=machine_id,
        completed_at=completed_at,
        occurred_at=completed_at,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-concurrency",
        form_token=form_token,
    )


def test_concurrent_appends_same_expected_version_have_one_winner(
    mongo_database: Database,
) -> None:
    event_store = MongoEventStore.from_collection(mongo_database["machine_events"])
    machine_id = MachineId("vm-concurrent-append")
    seed = _revision_completed_event(
        machine_id=machine_id,
        event_id="evt-seed",
        form_token="token-seed",
    )
    event_store.append(seed, expected_version=0)

    event_a = _revision_completed_event(
        machine_id=machine_id,
        event_id="evt-a",
        form_token="token-a",
    )
    event_b = _revision_completed_event(
        machine_id=machine_id,
        event_id="evt-b",
        form_token="token-b",
    )
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def append_event(event: RevisionCompleted) -> None:
        barrier.wait()
        try:
            event_store.append(event, expected_version=1)
            with lock:
                outcomes.append("ok")
        except EventStoreConcurrencyError:
            with lock:
                outcomes.append("conflict")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(append_event, event_a),
            executor.submit(append_event, event_b),
        ]
        for future in as_completed(futures):
            future.result()

    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 1

    stored_events = event_store.get_events_for_machine(machine_id)
    assert len(stored_events) == 2
    winner_ids = {event.event_id.value for event in stored_events}
    assert "evt-seed" in winner_ids
    assert ("evt-a" in winner_ids) ^ ("evt-b" in winner_ids)

    versions = [
        document["aggregate_version"]
        for document in mongo_database["machine_events"].find(
            {"aggregate_id": machine_id.value},
            sort=[("aggregate_version", 1)],
        )
    ]
    assert versions == [1, 2]


def test_concurrent_append_same_event_id_is_idempotent(
    mongo_database: Database,
) -> None:
    event_store = MongoEventStore.from_collection(mongo_database["machine_events"])
    machine_id = MachineId("vm-concurrent-idempotent")
    event = _revision_completed_event(
        machine_id=machine_id,
        event_id="evt-idempotent",
        form_token="token-idempotent",
    )
    barrier = threading.Barrier(2)

    def append_event() -> None:
        barrier.wait()
        event_store.append(event, expected_version=0)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(append_event), executor.submit(append_event)]
        for future in as_completed(futures):
            future.result()

    stored_events = event_store.get_events_for_machine(machine_id)
    assert len(stored_events) == 1
    assert stored_events[0].event_id.value == "evt-idempotent"

    document_count = mongo_database["machine_events"].count_documents(
        {"event_id": "evt-idempotent"},
    )
    assert document_count == 1
