from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.domain.events import DomainEvent
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations import (
    CompleteRevision,
    LoadingSubmitted,
    MachineOperations,
    RevisionCompleted,
    SubmitLoading,
)
from src.domain.models import PrefilledFormLink, RevisionSource
from src.infrastructure.memory import (
    EventSourcedMachineOperationsRepository,
    InMemoryEventStore,
)

_MACHINE_ID = MachineId("vm-01")
_TECH_A = TechnicianId("tech-a")
_REVISION_FORM_LINK = PrefilledFormLink(url="https://example.com/forms/revision")
_COMPLETED_AT = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _RecordingEventStore(InMemoryEventStore):
    append_calls: list[tuple[DomainEvent, int]] = field(default_factory=list)

    def append(self, event: DomainEvent, *, expected_version: int) -> None:
        self.append_calls.append((event, expected_version))
        InMemoryEventStore.append(self, event, expected_version=expected_version)


def _revision_completed(*, event_id: str, form_token: str) -> RevisionCompleted:
    return RevisionCompleted(
        event_id=EventId(event_id),
        revision_id=RevisionId(f"rev-{event_id}"),
        technician_id=_TECH_A,
        machine_id=_MACHINE_ID,
        completed_at=_COMPLETED_AT,
        occurred_at=_COMPLETED_AT,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-revision",
        form_token=form_token,
    )


def _seed_loading(
    repository: EventSourcedMachineOperationsRepository,
    *,
    form_token: str = "token-rev-1",
) -> None:
    aggregate = repository.get(_MACHINE_ID)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH_A,
            submitted_at=_COMPLETED_AT - timedelta(minutes=1),
            form_id="form-loading",
            form_token=f"load-before-{form_token}",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)


def test_repository_save_and_reload_preserves_capabilities() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)

    aggregate = repository.get(_MACHINE_ID)
    onboarding = aggregate.get_service_capabilities(
        _TECH_A,
        revision_form_link=_REVISION_FORM_LINK,
    )
    assert onboarding.responsibility_phase == "awaiting_handover"

    _seed_loading(repository)
    aggregate = repository.get(_MACHINE_ID)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH_A,
            completed_at=_COMPLETED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert isinstance(result, RevisionCompleted)
    repository.save(aggregate)

    reloaded = repository.get(_MACHINE_ID)
    active = reloaded.get_service_capabilities(
        _TECH_A,
        revision_form_link=_REVISION_FORM_LINK,
    )
    assert active.responsibility_phase == "responsible"

    second_load = repository.get(_MACHINE_ID)
    assert (
        second_load.get_service_capabilities(
            _TECH_A,
            revision_form_link=_REVISION_FORM_LINK,
        )
        == active
    )


def test_repository_save_keeps_pending_events_on_aggregate() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)

    _seed_loading(repository)
    aggregate = repository.get(_MACHINE_ID)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH_A,
            completed_at=_COMPLETED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert isinstance(result, RevisionCompleted)
    repository.save(aggregate)

    assert len(aggregate.collect_events()) == 1
    assert len(event_store.get_events_for_machine(_MACHINE_ID)) == 2


def test_repository_idempotent_save_does_not_duplicate_events() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)

    _seed_loading(repository)
    aggregate = repository.get(_MACHINE_ID)
    command = CompleteRevision(
        technician_id=_TECH_A,
        completed_at=_COMPLETED_AT,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-revision",
        form_token="token-rev-1",
    )
    first_event = aggregate.complete_revision(command)
    assert isinstance(first_event, RevisionCompleted)
    repository.save(aggregate)

    reloaded = repository.get(_MACHINE_ID)
    second_event = reloaded.complete_revision(command)
    repository.save(reloaded)

    assert second_event is first_event
    assert len(event_store.get_events_for_machine(_MACHINE_ID)) == 2


def test_repository_rehydrate_exposes_loaded_version() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)

    empty = repository.get(_MACHINE_ID)
    assert empty.loaded_version == 0

    _seed_loading(repository)
    aggregate = repository.get(_MACHINE_ID)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH_A,
            completed_at=_COMPLETED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert isinstance(result, RevisionCompleted)
    repository.save(aggregate)

    reloaded = repository.get(_MACHINE_ID)
    assert reloaded.loaded_version == 2


def test_repository_save_passes_loaded_version_as_expected_version() -> None:
    event_store = _RecordingEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)

    seed = _revision_completed(event_id="evt-seed", form_token="token-seed")
    event_store.append(seed, expected_version=0)

    aggregate = repository.get(_MACHINE_ID)
    assert aggregate.loaded_version == 1
    pending = _revision_completed(event_id="evt-next", form_token="token-next")
    aggregate._pending_events.append(pending)
    repository.save(aggregate)

    assert len(event_store.append_calls) == 2
    saved_event, expected_version = event_store.append_calls[1]
    assert saved_event.event_id == pending.event_id
    assert expected_version == 1


def test_repository_rejects_more_than_one_pending_event() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)

    aggregate = MachineOperations.empty(_MACHINE_ID)
    aggregate._pending_events.append(
        _revision_completed(event_id="evt-a", form_token="token-a"),
    )
    aggregate._pending_events.append(
        _revision_completed(event_id="evt-b", form_token="token-b"),
    )

    with pytest.raises(ValueError, match="one event per save boundary"):
        repository.save(aggregate)


def test_duplicate_save_same_event_remains_idempotent() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)

    _seed_loading(repository)
    aggregate = repository.get(_MACHINE_ID)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH_A,
            completed_at=_COMPLETED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert isinstance(result, RevisionCompleted)
    repository.save(aggregate)
    repository.save(aggregate)

    assert len(event_store.get_events_for_machine(_MACHINE_ID)) == 2
