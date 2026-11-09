from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations import (
    CompleteMaintenance,
    CompleteRevision,
    LoadingSubmitted,
    MachineOperations,
    RevisionCompleted,
    SubmitLoading,
)
from src.domain.machine_operations.events import DomainEvent
from src.domain.models import PrefilledFormLink, RevisionSource
from src.domain.results import RevisionNotAllowed, ServiceCapabilities
from src.domain.revision_due_policy import compute_responsibility_expires_at

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


def test_capabilities_onboarding_without_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.responsibility_phase == "awaiting_handover"
    assert caps.can_complete_revision is False
    assert caps.can_submit_loading is True
    assert caps.can_complete_maintenance is False
    assert caps.revision_form_link is None


def test_capabilities_onboarding_when_last_revision_by_other_technician() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_A)

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.responsibility_phase == "awaiting_handover"
    assert caps.can_complete_revision is False
    assert caps.can_submit_loading is True


def test_capabilities_handover_allows_loading() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_A)

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.responsibility_phase == "awaiting_handover"
    assert caps.can_submit_loading is True
    assert caps.loading_completed is False


def test_capabilities_handover_without_revision_allows_loading() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.can_submit_loading is True


def test_capabilities_handover_loading_completed_after_submit() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_A, completed_at=_T0)
    aggregate.submit_loading(
        _submit_loading_command(
            technician_id=_TECH_B,
            submitted_at=_T1,
        ),
    )

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.loading_completed is True


def test_capabilities_active_for_last_revision_technician() -> None:
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [_revision_completed_event(technician_id=_TECH_B)],
    )

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.responsibility_phase == "responsible"
    assert caps.can_complete_revision is False
    assert caps.can_submit_loading is True
    # ISS-018: complete ТО без загрузки; фото по-прежнему требуют loading_completed
    assert caps.can_complete_maintenance is True
    assert caps.can_submit_loading_photos is False
    assert caps.revision_form_link is None
    assert caps.loading_completed is False


def test_capabilities_active_maintenance_completed_today() -> None:
    today = datetime.now(tz=UTC)
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(
        aggregate,
        technician_id=_TECH_B,
        completed_at=today,
    )
    aggregate.submit_loading(
        _submit_loading_command(technician_id=_TECH_B, submitted_at=today),
    )
    aggregate.complete_maintenance(
        _complete_maintenance_command(technician_id=_TECH_B, completed_at=today),
        checked_at=today,
    )

    caps = _capabilities(aggregate, _TECH_B, checked_at=today)

    assert caps.maintenance_completed_today is True
    assert caps.can_complete_maintenance is False


def test_capabilities_active_loading_completed_after_submit() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_B)
    aggregate.submit_loading(
        _submit_loading_command(technician_id=_TECH_B, submitted_at=_T1),
    )

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.loading_completed is True
    assert caps.can_complete_maintenance is True
    assert caps.can_submit_loading_photos is True


def test_capabilities_photos_blocked_until_loading_complete_allowed() -> None:
    # ISS-018: photos still need loading; complete ТО — нет
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [_revision_completed_event(technician_id=_TECH_B)],
    )

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.loading_completed is False
    assert caps.can_submit_loading is True
    assert caps.can_submit_loading_photos is False
    assert caps.can_complete_maintenance is True


def test_revision_without_loading_not_allowed() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    result = aggregate.complete_revision(_complete_revision_command())

    assert isinstance(result, RevisionNotAllowed)
    assert aggregate.collect_events() == []


def test_handover_loading_credits_photos_after_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_A, completed_at=_T0)
    aggregate.clear_pending_events()
    loading = aggregate.submit_loading(
        _submit_loading_command(
            form_token="token-load-handover",
            technician_id=_TECH_B,
            submitted_at=_T1,
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    revision = aggregate.complete_revision(
        _complete_revision_command(
            form_token="token-rev-b",
            technician_id=_TECH_B,
            completed_at=_T2,
        ),
    )
    assert isinstance(revision, RevisionCompleted)

    caps = _capabilities(aggregate, _TECH_B)

    assert caps.responsibility_phase == "responsible"
    assert caps.loading_completed is True
    assert caps.can_submit_loading_photos is True
    assert caps.can_complete_maintenance is True


def test_responsible_never_can_complete_revision() -> None:
    expires_at = datetime(2026, 5, 25, 0, 0, tzinfo=_MSK)
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [
            _revision_completed_event(
                technician_id=_TECH_A,
                responsibility_expires_at=expires_at,
            )
        ],
        revision_interval_min_days=10,
        revision_interval_max_days=12,
    )
    soft_window = expires_at - timedelta(days=1)
    caps = aggregate.get_service_capabilities(
        _TECH_A,
        checked_at=soft_window,
        revision_form_link=_REVISION_FORM_LINK,
    )

    assert caps.responsibility_phase == "responsible"
    assert caps.revision_due_status == "not_due"
    assert caps.can_complete_revision is False
    assert caps.revision_form_link is None
    result = aggregate.complete_revision(
        _complete_revision_command(
            technician_id=_TECH_A,
            completed_at=soft_window,
            form_token="token-rev-soft",
        ),
    )
    assert isinstance(result, RevisionNotAllowed)


def test_complete_revision_records_event_and_updates_last_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    event = _complete_revision(aggregate)

    assert isinstance(event, RevisionCompleted)
    assert event.form_token == "token-rev-1"
    assert len(aggregate.collect_events()) == 2


def test_complete_revision_is_idempotent_for_same_form_token() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    command = _complete_revision_command()
    aggregate.submit_loading(
        _submit_loading_command(
            form_token="load-before-token-rev-1",
            submitted_at=_T0 - timedelta(minutes=1),
        ),
    )

    first = aggregate.complete_revision(command)
    aggregate.clear_pending_events()
    second = aggregate.complete_revision(command)

    assert second is first
    assert aggregate.collect_events() == []


def test_rehydrate_matches_incremental_operations() -> None:
    events: list[DomainEvent] = []
    incremental = MachineOperations.empty(_MACHINE_ID)

    _complete_revision(
        incremental,
        form_token="token-1",
        completed_at=_T0,
    )
    events.extend(incremental.collect_events())
    incremental.clear_pending_events()

    load_b = incremental.submit_loading(
        _submit_loading_command(
            form_token="load-before-token-2",
            technician_id=_TECH_B,
            submitted_at=_T1,
        ),
    )
    assert isinstance(load_b, LoadingSubmitted)
    events.append(load_b)
    incremental.clear_pending_events()

    rev_b = incremental.complete_revision(
        _complete_revision_command(
            form_token="token-2",
            technician_id=_TECH_B,
            completed_at=_T2,
        ),
    )
    assert isinstance(rev_b, RevisionCompleted)
    events.append(rev_b)

    replayed = MachineOperations.rehydrate(_MACHINE_ID, events)

    assert _capabilities(replayed, _TECH_A) == _capabilities(incremental, _TECH_A)
    assert _capabilities(replayed, _TECH_B) == _capabilities(incremental, _TECH_B)


def test_rehydrate_uses_latest_revision_by_completed_at() -> None:
    older = _revision_completed_event(
        form_token="older",
        completed_at=_T0,
        revision_id="rev-old",
        event_id="event-old",
    )
    newer = _revision_completed_event(
        form_token="newer",
        technician_id=_TECH_B,
        completed_at=_T2,
        revision_id="rev-new",
        event_id="event-new",
    )

    aggregate = MachineOperations.rehydrate(_MACHINE_ID, [newer, older])

    assert _capabilities(aggregate, _TECH_B).responsibility_phase == "responsible"
    assert _capabilities(aggregate, _TECH_A).responsibility_phase == "awaiting_handover"


def test_revision_becomes_stale_at_or_after_interval_days() -> None:
    interval_days = 7
    aggregate = MachineOperations.empty(
        _MACHINE_ID,
        responsibility_period_days=interval_days,
        service_calendar_timezone=_MSK,
    )
    event = _complete_revision(
        aggregate,
        technician_id=_TECH_A,
        completed_at=_T0,
    )
    assert event.responsibility_expires_at is not None
    expires_at = event.responsibility_expires_at
    before_boundary = expires_at - timedelta(seconds=1)

    assert aggregate.responsibility_phase(_TECH_A, checked_at=before_boundary) == "responsible"
    assert aggregate.responsibility_phase(_TECH_A, checked_at=expires_at) == "awaiting_handover"


def test_new_revision_after_stale_interval_returns_to_active_phase() -> None:
    interval_days = 7
    aggregate = MachineOperations.empty(_MACHINE_ID, responsibility_period_days=interval_days)
    _complete_revision(
        aggregate,
        technician_id=_TECH_A,
        completed_at=_T0,
    )
    aggregate.clear_pending_events()

    stale_time = _T0 + timedelta(days=interval_days)
    assert aggregate.responsibility_phase(_TECH_A, checked_at=stale_time) == "awaiting_handover"

    loading = aggregate.submit_loading(
        _submit_loading_command(
            form_token="load-before-token-rev-stale-refresh",
            technician_id=_TECH_A,
            submitted_at=stale_time - timedelta(minutes=1),
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    result = aggregate.complete_revision(
        _complete_revision_command(
            technician_id=_TECH_A,
            completed_at=stale_time,
            form_token="token-rev-stale-refresh",
        ),
    )

    assert isinstance(result, RevisionCompleted)
    assert aggregate.responsibility_phase(_TECH_A, checked_at=stale_time) == "responsible"


def test_complete_revision_persists_responsibility_expires_at() -> None:
    aggregate = MachineOperations.empty(
        _MACHINE_ID,
        revision_interval_min_days=10,
        revision_interval_max_days=12,
        service_calendar_timezone=_MSK,
    )
    _complete_revision(aggregate, technician_id=_TECH_A, completed_at=_T0)
    event = aggregate.collect_events()[-1]
    assert isinstance(event, RevisionCompleted)
    assert event.responsibility_expires_at is not None
    expected = compute_responsibility_expires_at(
        machine_id=_MACHINE_ID,
        revision_id=event.revision_id,
        completed_at=_T0,
        min_days=10,
        max_days=12,
        service_calendar_timezone=_MSK,
    )
    assert event.responsibility_expires_at == expected


def test_legacy_revision_without_expires_at_uses_completed_at_plus_min_days() -> None:
    event = _revision_completed_event(completed_at=_T0, responsibility_expires_at=None)
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [event],
        revision_interval_min_days=7,
        revision_interval_max_days=7,
    )
    before = _T0 + timedelta(days=7) - timedelta(seconds=1)
    at = _T0 + timedelta(days=7)
    assert aggregate.responsibility_phase(_TECH_A, checked_at=before) == "responsible"
    assert aggregate.responsibility_phase(_TECH_A, checked_at=at) == "awaiting_handover"


def test_not_due_does_not_block_loading() -> None:
    expires_at = datetime(2026, 5, 25, 0, 0, tzinfo=_MSK)
    event = _revision_completed_event(
        completed_at=_T0,
        responsibility_expires_at=expires_at,
    )
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [event],
        revision_interval_min_days=10,
        revision_interval_max_days=12,
    )
    checked_at = expires_at - timedelta(days=1)
    assert aggregate.revision_due_status(checked_at=checked_at) == "not_due"
    result = aggregate.submit_loading(
        _submit_loading_command(technician_id=_TECH_A, submitted_at=checked_at),
    )
    assert isinstance(result, LoadingSubmitted)


def test_overdue_handover_requires_loading_before_revision() -> None:
    expires_at = datetime(2026, 5, 25, 0, 0, tzinfo=_MSK)
    event = _revision_completed_event(
        completed_at=_T0,
        responsibility_expires_at=expires_at,
    )
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [event],
        revision_interval_min_days=10,
        revision_interval_max_days=12,
    )
    overdue_at = expires_at
    assert aggregate.revision_due_status(checked_at=overdue_at) == "overdue"
    assert aggregate.responsibility_phase(_TECH_A, checked_at=overdue_at) == "awaiting_handover"
    caps = aggregate.get_service_capabilities(
        _TECH_A,
        checked_at=overdue_at,
        revision_form_link=_REVISION_FORM_LINK,
    )
    assert caps.can_complete_revision is False
    assert caps.revision_due_status is None
    denied = aggregate.complete_revision(
        _complete_revision_command(
            technician_id=_TECH_A,
            completed_at=overdue_at,
            form_token="token-rev-overdue-no-load",
        ),
    )
    assert isinstance(denied, RevisionNotAllowed)


def test_service_capabilities_include_revision_outlook() -> None:
    expires_at = datetime(2026, 5, 25, 0, 0, tzinfo=UTC)
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [_revision_completed_event(responsibility_expires_at=expires_at)],
        revision_interval_min_days=10,
        revision_interval_max_days=12,
    )
    caps = aggregate.get_service_capabilities(_TECH_A, checked_at=_T0)
    assert caps.responsibility_expires_at == expires_at
    assert caps.revision_due_status == "not_due"


def test_last_revision_accessors_after_complete_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    completed_at = datetime(2026, 6, 10, 14, 0, tzinfo=UTC)
    event = _complete_revision(aggregate, technician_id=_TECH_A, completed_at=completed_at)

    assert aggregate.last_revision_id() == event.revision_id
    assert aggregate.last_revision_opened_by() == _TECH_A
    assert aggregate.last_revision_opened_at() == completed_at


def test_last_revision_accessors_return_none_without_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    assert aggregate.last_revision_id() is None
    assert aggregate.last_revision_opened_by() is None
    assert aggregate.last_revision_opened_at() is None


def test_awaiting_handover_without_revision_link_raises() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    with pytest.raises(ValueError, match="revision_form_link is required"):
        aggregate.get_service_capabilities(_TECH_A, checked_at=_CHECKED_AT)


def test_awaiting_handover_allows_missing_revision_form() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    caps = aggregate.get_service_capabilities(
        _TECH_A,
        checked_at=_CHECKED_AT,
        allow_missing_revision_form=True,
    )

    assert caps.responsibility_phase == "awaiting_handover"
    assert caps.can_complete_revision is False
    assert caps.revision_form_link is None
    assert caps.can_submit_loading is False
    assert caps.can_complete_maintenance is True
    assert caps.can_submit_loading_photos is True


def test_loading_completed_false_when_loading_on_previous_operational_day() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_B, completed_at=_T0)
    aggregate.submit_loading(
        _submit_loading_command(technician_id=_TECH_B, submitted_at=_T1),
    )
    next_ops_day = datetime(2026, 5, 16, 10, 0, tzinfo=UTC)

    caps = _capabilities(aggregate, _TECH_B, checked_at=next_ops_day)

    assert caps.loading_completed is False
    assert caps.can_submit_loading_photos is False


def test_loading_completed_ignores_other_technician_same_day() -> None:
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [_revision_completed_event(technician_id=_TECH_B, completed_at=_T0)],
    )
    aggregate.submit_loading(
        _submit_loading_command(technician_id=_TECH_A, submitted_at=_T1),
    )

    caps = _capabilities(aggregate, _TECH_B, checked_at=_CHECKED_AT)

    assert caps.loading_completed is False


def test_overdue_mid_period_loading_does_not_credit_new_handover_day() -> None:
    expires_at = datetime(2026, 5, 25, 0, 0, tzinfo=_MSK)
    revision = _revision_completed_event(
        technician_id=_TECH_A,
        completed_at=_T0,
        responsibility_expires_at=expires_at,
    )
    mid_period_load = _loading_submitted_event(
        technician_id=_TECH_A,
        submitted_at=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
        form_token="token-load-mid",
        event_id="event-load-mid",
    )
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [revision, mid_period_load],
        revision_interval_min_days=10,
        revision_interval_max_days=12,
    )
    overdue_next_day = datetime(2026, 5, 26, 10, 0, tzinfo=UTC)

    caps = aggregate.get_service_capabilities(
        _TECH_A,
        checked_at=overdue_next_day,
        revision_form_link=_REVISION_FORM_LINK,
    )

    assert caps.responsibility_phase == "awaiting_handover"
    assert caps.loading_completed is False
    assert caps.can_complete_revision is False
    denied = aggregate.complete_revision(
        _complete_revision_command(
            technician_id=_TECH_A,
            completed_at=overdue_next_day,
            form_token="token-rev-overdue-stale-load",
        ),
    )
    assert isinstance(denied, RevisionNotAllowed)
