from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pymongo.database import Database

from src.application.machine_operations.errors import MachineOperationsConcurrencyError
from src.application.machine_operations.executor import MachineOperationsExecutor
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations import CompleteRevision, MachineOperations, RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.memory import EventSourcedMachineOperationsRepository
from src.infrastructure.mongodb import MongoEventStore

pytestmark = pytest.mark.integration


def test_stale_machine_decision_is_rejected_and_executor_reloads(
    mongo_database: Database,
) -> None:
    event_store = MongoEventStore.from_collection(mongo_database["machine_events"])
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    machine_id = MachineId("vm-stale-reload")
    completed_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)

    aggregate_a = repository.get(machine_id)
    aggregate_b = repository.get(machine_id)
    assert aggregate_a.loaded_version == 0
    assert aggregate_b.loaded_version == 0

    result_a = aggregate_a.complete_revision(
        CompleteRevision(
            technician_id=TechnicianId("tech-a"),
            completed_at=completed_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-a",
        ),
    )
    assert isinstance(result_a, RevisionCompleted)
    repository.save(aggregate_a)

    result_b = aggregate_b.complete_revision(
        CompleteRevision(
            technician_id=TechnicianId("tech-b"),
            completed_at=completed_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-b-stale",
        ),
    )
    assert isinstance(result_b, RevisionCompleted)
    stale_event_id = result_b.event_id.value
    with pytest.raises(MachineOperationsConcurrencyError):
        repository.save(aggregate_b)

    observed_versions: list[int] = []

    def command_fn(aggregate: MachineOperations) -> RevisionCompleted | object:
        observed_versions.append(aggregate.loaded_version)
        return aggregate.complete_revision(
            CompleteRevision(
                technician_id=TechnicianId("tech-b"),
                completed_at=datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-revision",
                form_token="token-b-reload",
            ),
        )

    executor = MachineOperationsExecutor(repository=repository, max_save_retries=5)
    reloaded_result = executor.execute(machine_id, command_fn)
    assert isinstance(reloaded_result, RevisionCompleted)
    assert observed_versions == [1]

    durable = event_store.get_events_for_machine(machine_id)
    assert len(durable) == 2
    assert durable[0].event_id == result_a.event_id
    assert durable[1].event_id == reloaded_result.event_id
    assert all(event.event_id.value != stale_event_id for event in durable)

    versions = [
        document["aggregate_version"]
        for document in mongo_database["machine_events"].find(
            {"aggregate_id": machine_id.value},
            sort=[("aggregate_version", 1)],
        )
    ]
    assert versions == [1, 2]
