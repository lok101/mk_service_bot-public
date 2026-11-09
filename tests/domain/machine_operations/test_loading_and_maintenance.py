from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations import (
    CompleteMaintenance,
    CompleteRevision,
    LoadingSubmitted,
    MachineOperations,
    MaintenanceCompleted,
    RevisionCompleted,
    SubmitLoading,
)
from src.domain.models import PrefilledFormLink, RevisionSource
from src.domain.results import (
    LOADING_NOT_ALLOWED_REASON,
    MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
    MAINTENANCE_NOT_ALLOWED_REASON,
    LoadingNotAllowed,
    MaintenanceAlreadyCompletedToday,
    MaintenanceNotAllowed,
    ServiceCapabilities,
)

_MACHINE_ID = MachineId("vm-01")
_TECH_A = TechnicianId("tech-a")
_TECH_B = TechnicianId("tech-b")
_REVISION_FORM_LINK = PrefilledFormLink(url="https://example.com/forms/revision")
_T0 = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 5, 15, 11, 0, tzinfo=UTC)
_T2 = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
_CHECKED_AT = datetime(2026, 5, 15, 13, 0, tzinfo=UTC)
_MSK = ZoneInfo("Europe/Moscow")


def _capabilities(
    aggregate: MachineOperations,
    technician_id: TechnicianId,
    *,
    checked_at: datetime = _CHECKED_AT,
) -> ServiceCapabilities:
    return aggregate.get_service_capabilities(
        technician_id,
        checked_at=checked_at,
        revision_form_link=_REVISION_FORM_LINK,
    )


def _complete_revision_command(
    *,
    form_token: str = "token-rev-1",
    technician_id: TechnicianId = _TECH_A,
    completed_at: datetime = _T0,
) -> CompleteRevision:
    return CompleteRevision(
        technician_id=technician_id,
        completed_at=completed_at,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-revision",
        form_token=form_token,
    )


def _submit_loading_command(
    *,
    form_token: str = "token-load-1",
    technician_id: TechnicianId = _TECH_A,
    submitted_at: datetime = _T0,
) -> SubmitLoading:
    return SubmitLoading(
        technician_id=technician_id,
        submitted_at=submitted_at,
        form_id="form-loading",
        form_token=form_token,
    )


def _revision_completed_event(
    *,
    form_token: str = "token-rev-1",
    technician_id: TechnicianId = _TECH_A,
    completed_at: datetime = _T0,
    revision_id: str = "rev-1",
    event_id: str = "event-rev-1",
    responsibility_expires_at: datetime | None = None,
) -> RevisionCompleted:
    return RevisionCompleted(
        event_id=EventId(event_id),
        revision_id=RevisionId(revision_id),
        technician_id=technician_id,
        machine_id=_MACHINE_ID,
        completed_at=completed_at,
        occurred_at=completed_at,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-revision",
        form_token=form_token,
        responsibility_expires_at=responsibility_expires_at,
    )


def _loading_submitted_event(
    *,
    form_token: str = "token-load-1",
    technician_id: TechnicianId = _TECH_A,
    submitted_at: datetime = _T0,
    event_id: str = "event-load-1",
) -> LoadingSubmitted:
    return LoadingSubmitted(
        event_id=EventId(event_id),
        technician_id=technician_id,
        machine_id=_MACHINE_ID,
        submitted_at=submitted_at,
        occurred_at=submitted_at,
        form_id="form-loading",
        form_token=form_token,
    )


def _complete_revision(
    aggregate: MachineOperations,
    *,
    form_token: str = "token-rev-1",
    technician_id: TechnicianId = _TECH_A,
    completed_at: datetime = _T0,
) -> RevisionCompleted:
    loading = aggregate.submit_loading(
        _submit_loading_command(
            form_token=f"load-before-{form_token}",
            technician_id=technician_id,
            submitted_at=completed_at - timedelta(minutes=1),
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    result = aggregate.complete_revision(
        _complete_revision_command(
            form_token=form_token,
            technician_id=technician_id,
            completed_at=completed_at,
        ),
    )
    assert isinstance(result, RevisionCompleted)
    return result


def _complete_maintenance_command(
    *,
    technician_id: TechnicianId = _TECH_A,
    completed_at: datetime = _T0,
) -> CompleteMaintenance:
    return CompleteMaintenance(
        technician_id=technician_id,
        completed_at=completed_at,
    )


def test_submit_loading_allowed_in_handover_after_other_technician_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_A, completed_at=_T0)
    aggregate.clear_pending_events()

    result = aggregate.submit_loading(
        _submit_loading_command(
            technician_id=_TECH_B,
            submitted_at=_T1,
        ),
    )

    assert isinstance(result, LoadingSubmitted)
    assert len(aggregate.collect_events()) == 1


def test_submit_loading_allowed_in_handover_without_prior_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    aggregate.clear_pending_events()

    result = aggregate.submit_loading(
        _submit_loading_command(
            technician_id=_TECH_B,
            submitted_at=_T0,
        ),
    )

    assert isinstance(result, LoadingSubmitted)


def test_submit_loading_rejected_in_handover_when_not_after_last_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_A, completed_at=_T0)
    aggregate.clear_pending_events()

    at_revision_time = aggregate.submit_loading(
        _submit_loading_command(
            technician_id=_TECH_B,
            submitted_at=_T0,
        ),
    )
    before_revision = aggregate.submit_loading(
        _submit_loading_command(
            technician_id=_TECH_B,
            submitted_at=_T0 - timedelta(seconds=1),
            form_token="token-load-too-early",
        ),
    )

    assert isinstance(at_revision_time, LoadingNotAllowed)
    assert isinstance(before_revision, LoadingNotAllowed)
    assert aggregate.collect_events() == []


def test_submit_loading_rejected_in_handover_at_revision_timestamp() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_A)
    aggregate.clear_pending_events()

    result = aggregate.submit_loading(_submit_loading_command(technician_id=_TECH_B))

    assert isinstance(result, LoadingNotAllowed)
    assert result.reason == LOADING_NOT_ALLOWED_REASON
    assert aggregate.collect_events() == []


def test_submit_loading_allowed_for_handover_technician_after_other_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_B)

    result = aggregate.submit_loading(
        _submit_loading_command(
            technician_id=_TECH_A,
            submitted_at=_T1,
        ),
    )

    assert isinstance(result, LoadingSubmitted)


def test_submit_loading_records_event_in_active_phase() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, completed_at=_T0)
    aggregate.clear_pending_events()

    event = aggregate.submit_loading(
        _submit_loading_command(submitted_at=_T1),
    )

    assert isinstance(event, LoadingSubmitted)
    assert len(aggregate.collect_events()) == 1

    caps = _capabilities(aggregate, _TECH_A)
    assert caps.loading_completed is True


def test_complete_maintenance_records_event_in_active_phase() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)
    aggregate.submit_loading(_submit_loading_command(submitted_at=_T1))
    aggregate.clear_pending_events()

    result = aggregate.complete_maintenance(
        _complete_maintenance_command(completed_at=_T1),
        checked_at=_CHECKED_AT,
    )

    assert isinstance(result, MaintenanceCompleted)
    assert result.completed_at == _T1
    assert aggregate.last_maintenance_completed_at() == _T1


def test_complete_maintenance_without_loading_succeeds_when_responsible() -> None:
    # ISS-018: пропуск формы загрузки разрешает завершение ТО
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [_revision_completed_event(technician_id=_TECH_A, completed_at=_T0)],
    )
    assert _capabilities(aggregate, _TECH_A).loading_completed is False

    result = aggregate.complete_maintenance(
        _complete_maintenance_command(completed_at=_T1),
        checked_at=_CHECKED_AT,
    )

    assert isinstance(result, MaintenanceCompleted)
    assert result.completed_at == _T1
    assert _capabilities(aggregate, _TECH_A).loading_completed is False


def test_complete_maintenance_rejected_in_onboarding() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    result = aggregate.complete_maintenance(
        _complete_maintenance_command(),
        checked_at=_CHECKED_AT,
    )

    assert isinstance(result, MaintenanceNotAllowed)
    assert result.reason == MAINTENANCE_NOT_ALLOWED_REASON


def test_complete_maintenance_rejects_second_completion_on_same_day() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)
    aggregate.submit_loading(_submit_loading_command(submitted_at=_T0))
    first = aggregate.complete_maintenance(
        _complete_maintenance_command(completed_at=_T0),
        checked_at=_T0,
    )
    assert isinstance(first, MaintenanceCompleted)
    aggregate.clear_pending_events()

    second = aggregate.complete_maintenance(
        _complete_maintenance_command(completed_at=_T1),
        checked_at=_T1,
    )

    assert isinstance(second, MaintenanceAlreadyCompletedToday)
    assert second.reason == MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON


def test_rehydrate_applies_loading_submitted_for_historical_events() -> None:
    revision = _revision_completed_event(form_token="rev-1", completed_at=_T0)
    loading = _loading_submitted_event(
        form_token="load-1",
        technician_id=_TECH_B,
        submitted_at=_T1,
    )
    aggregate = MachineOperations.rehydrate(_MACHINE_ID, [revision, loading])

    assert _capabilities(aggregate, _TECH_A).responsibility_phase == "responsible"
    assert _capabilities(aggregate, _TECH_B).responsibility_phase == "awaiting_handover"

    result = aggregate.complete_revision(
        _complete_revision_command(
            technician_id=_TECH_B,
            completed_at=_T2,
            form_token="rev-b",
        ),
    )

    assert isinstance(result, RevisionCompleted)
    assert _capabilities(aggregate, _TECH_B).responsibility_phase == "responsible"
