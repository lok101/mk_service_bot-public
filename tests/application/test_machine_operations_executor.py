from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.machine_operations.errors import MachineOperationsConcurrencyError
from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import RegisterRevisionFromFormService
from src.application.machine_operations.use_cases import RegisterRevisionFromFormCommand
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations import (
    CompleteRevision,
    LoadingSubmitted,
    MachineOperations,
    RevisionCompleted,
    SubmitLoading,
)
from src.domain.models import RevisionSource
from src.infrastructure.memory import (
    EventSourcedMachineOperationsRepository,
    InMemoryEventStore,
)

_TECH = TechnicianId("tech-a")
_COMPLETED_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)


class _FlakyMachineOperationsRepository:
    def __init__(self, inner: EventSourcedMachineOperationsRepository) -> None:
        self._inner = inner
        self.save_calls = 0

    def get(self, machine_id: MachineId) -> MachineOperations:
        return self._inner.get(machine_id)

    def save(self, aggregate: MachineOperations) -> None:
        self.save_calls += 1
        if self.save_calls < 3:
            raise MachineOperationsConcurrencyError("simulated race")
        self._inner.save(aggregate)


class _RaceInjectingRepository:
    def __init__(
        self,
        inner: EventSourcedMachineOperationsRepository,
        event_store: InMemoryEventStore,
    ) -> None:
        self._inner = inner
        self._event_store = event_store
        self.save_calls = 0
        self._injected = False

    def get(self, machine_id: MachineId) -> MachineOperations:
        return self._inner.get(machine_id)

    def save(self, aggregate: MachineOperations) -> None:
        self.save_calls += 1
        if not self._injected:
            self._injected = True
            competing = RevisionCompleted(
                event_id=EventId("evt-competing"),
                revision_id=RevisionId("rev-competing"),
                technician_id=TechnicianId("tech-b"),
                machine_id=aggregate.machine_id,
                completed_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
                occurred_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-competing",
                form_token="token-competing",
            )
            self._event_store.append(
                competing,
                expected_version=aggregate.loaded_version,
            )
        self._inner.save(aggregate)


def _seed_loading(
    repository: EventSourcedMachineOperationsRepository,
    machine_id: MachineId,
    *,
    form_token: str,
    completed_at: datetime = _COMPLETED_AT,
) -> None:
    aggregate = repository.get(machine_id)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH,
            submitted_at=completed_at - timedelta(minutes=1),
            form_id="form-loading",
            form_token=f"load-before-{form_token}",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)


def test_executor_reloads_and_reexecutes_command_after_expected_version_conflict() -> None:
    event_store = InMemoryEventStore()
    inner = EventSourcedMachineOperationsRepository(event_store=event_store)
    machine_id = MachineId("vm-race-reload")
    _seed_loading(inner, machine_id, form_token="token-stale-decision")
    race = _RaceInjectingRepository(inner, event_store)
    executor = MachineOperationsExecutor(repository=race, max_save_retries=5)
    observed_versions: list[int] = []
    stale_event_ids: list[str] = []

    def command_fn(aggregate: MachineOperations) -> RevisionCompleted | object:
        observed_versions.append(aggregate.loaded_version)
        result = aggregate.complete_revision(
            CompleteRevision(
                technician_id=_TECH,
                completed_at=_COMPLETED_AT,
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-revision",
                form_token="token-stale-decision",
            ),
        )
        if isinstance(result, RevisionCompleted):
            stale_event_ids.append(result.event_id.value)
        return result

    result = executor.execute(machine_id, command_fn)

    assert isinstance(result, RevisionCompleted)
    assert observed_versions == [1, 2]
    assert race.save_calls == 2
    durable = event_store.get_events_for_machine(machine_id)
    assert len(durable) == 3
    assert durable[1].event_id.value == "evt-competing"
    assert durable[2].event_id == result.event_id
    assert stale_event_ids[0] != result.event_id.value
    assert all(event.event_id.value != stale_event_ids[0] for event in durable)


class _CollectingPublisher:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    def publish(self, event: RevisionCompleted) -> None:
        self.event_ids.append(event.event_id.value)


def test_executor_retries_save_after_concurrency_error() -> None:
    event_store = InMemoryEventStore()
    inner = EventSourcedMachineOperationsRepository(event_store=event_store)
    machine_id = MachineId("vm-retry")
    submitted_at = _COMPLETED_AT
    _seed_loading(inner, machine_id, form_token="token-retry", completed_at=submitted_at)
    flaky = _FlakyMachineOperationsRepository(inner)
    service = RegisterRevisionFromFormService(
        executor=MachineOperationsExecutor(
            repository=flaky,
            max_save_retries=5,
        ),
    )
    result = service.execute(
        RegisterRevisionFromFormCommand(
            technician_id=_TECH,
            machine_id=machine_id,
            submitted_at=submitted_at,
            form_id="form-revision",
            form_token="token-retry",
        ),
    )

    assert isinstance(result, RevisionCompleted)
    assert flaky.save_calls == 3
    assert len(event_store.get_events_for_machine(machine_id)) == 2


def test_executor_raises_after_exhausted_retries() -> None:
    event_store = InMemoryEventStore()
    inner = EventSourcedMachineOperationsRepository(event_store=event_store)
    machine_id = MachineId("vm-fail")
    _seed_loading(inner, machine_id, form_token="token-fail")
    flaky = _FlakyMachineOperationsRepository(inner)
    executor = MachineOperationsExecutor(
        repository=flaky,
        max_save_retries=2,
    )

    with pytest.raises(MachineOperationsConcurrencyError):
        executor.execute(
            machine_id,
            lambda aggregate: aggregate.complete_revision(
                CompleteRevision(
                    technician_id=_TECH,
                    completed_at=_COMPLETED_AT,
                    source=RevisionSource.GOOGLE_FORM,
                    form_id="form-revision",
                    form_token="token-fail",
                ),
            ),
        )

    assert flaky.save_calls == 2
    assert len(event_store.get_events_for_machine(machine_id)) == 1


def test_executor_clears_pending_events_after_successful_publish() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    machine_id = MachineId("vm-publish")
    _seed_loading(repository, machine_id, form_token="token-publish")
    publisher = _CollectingPublisher()
    executor = MachineOperationsExecutor(repository=repository, publisher=publisher)

    captured: list[MachineOperations] = []
    result = executor.execute(
        machine_id,
        lambda _aggregate: (
            captured.append(_aggregate),
            _aggregate.complete_revision(
                CompleteRevision(
                    technician_id=_TECH,
                    completed_at=_COMPLETED_AT,
                    source=RevisionSource.GOOGLE_FORM,
                    form_id="form-revision",
                    form_token="token-publish",
                ),
            ),
        )[1],
    )

    assert isinstance(result, RevisionCompleted)
    assert captured and captured[0].collect_events() == []
    assert publisher.event_ids == [result.event_id.value]


def test_executor_republishes_idempotent_existing_event() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    machine_id = MachineId("vm-existing")
    _seed_loading(repository, machine_id, form_token="token-existing")
    publisher = _CollectingPublisher()
    executor = MachineOperationsExecutor(repository=repository, publisher=publisher)

    first = executor.execute(
        machine_id,
        lambda aggregate: aggregate.complete_revision(
            CompleteRevision(
                technician_id=_TECH,
                completed_at=_COMPLETED_AT,
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-revision",
                form_token="token-existing",
            ),
        ),
    )
    assert isinstance(first, RevisionCompleted)
    assert publisher.event_ids == [first.event_id.value]

    second = executor.execute(
        machine_id,
        lambda aggregate: aggregate.complete_revision(
            CompleteRevision(
                technician_id=_TECH,
                completed_at=_COMPLETED_AT,
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-revision",
                form_token="token-existing",
            ),
        ),
    )

    assert isinstance(second, RevisionCompleted)
    assert second.event_id == first.event_id
    assert publisher.event_ids == [first.event_id.value, first.event_id.value]
