from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.ids import BatchId, EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations import (
    CompleteMaintenance,
    CompleteRevision,
    LoadingSubmitted,
    MachineOperations,
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
    SubmitLoading,
    SubmitLoadingPhotos,
)
from src.domain.models import PrefilledFormLink, RevisionSource
from src.domain.photo_batch import PhotoRef
from src.domain.results import (
    LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
    LOADING_PHOTOS_INSUFFICIENT_COUNT_REASON,
    LOADING_PHOTOS_NOT_ALLOWED_REASON,
    LOADING_PHOTOS_REQUIRE_LOADING_REASON,
    LoadingPhotosAlreadySubmittedToday,
    LoadingPhotosInsufficientCount,
    LoadingPhotosNotAllowed,
    ServiceCapabilities,
)

_MACHINE_ID = MachineId("vm-01")
_TECH_A = TechnicianId("tech-a")
_TECH_B = TechnicianId("tech-b")
_REVISION_FORM_LINK = PrefilledFormLink(url="https://example.com/forms/revision")
_T0 = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 5, 15, 11, 0, tzinfo=UTC)
_T2 = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
_T_NEXT_DAY = datetime(2026, 5, 16, 10, 0, tzinfo=UTC)
_BATCH_ID = BatchId("batch-01")
_BATCH_ID_2 = BatchId("batch-02")
_PHOTO = PhotoRef(
    file_id="file-1",
    file_unique_id="unique-1",
    message_id=100,
)
_PHOTO_2 = PhotoRef(
    file_id="file-2",
    file_unique_id="unique-2",
    message_id=101,
)


_CHECKED_AT = datetime(2026, 5, 15, 13, 0, tzinfo=UTC)


def _capabilities(
    aggregate: MachineOperations,
    technician_id: TechnicianId,
    *,
    checked_at: datetime | None = _CHECKED_AT,
) -> ServiceCapabilities:
    return aggregate.get_service_capabilities(
        technician_id,
        checked_at=checked_at,
        revision_form_link=_REVISION_FORM_LINK,
    )


def _complete_revision(
    aggregate: MachineOperations,
    *,
    technician_id: TechnicianId = _TECH_A,
    completed_at: datetime = _T0,
    form_token: str = "token-rev-1",
) -> None:
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=technician_id,
            submitted_at=completed_at - timedelta(minutes=1),
            form_id="form-loading",
            form_token=f"load-before-{form_token}",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    aggregate.complete_revision(
        CompleteRevision(
            technician_id=technician_id,
            completed_at=completed_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token=form_token,
        ),
    )


def _submit_loading_photos_command(
    *,
    batch_id: BatchId = _BATCH_ID,
    technician_id: TechnicianId = _TECH_A,
    submitted_at: datetime = _T1,
    photos: tuple[PhotoRef, ...] = (_PHOTO, _PHOTO_2),
    min_photo_count: int = 2,
) -> SubmitLoadingPhotos:
    return SubmitLoadingPhotos(
        technician_id=technician_id,
        batch_id=batch_id,
        submitted_at=submitted_at,
        photos=photos,
        min_photo_count=min_photo_count,
    )


def test_submit_loading_photos_after_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)
    aggregate.clear_pending_events()

    result = aggregate.submit_loading_photos(_submit_loading_photos_command())

    assert isinstance(result, PhotosSubmitted)
    assert result.batch_id == _BATCH_ID
    assert result.photo_count == 2
    assert len(aggregate.collect_events()) == 1


def test_submit_loading_photos_emits_one_composite_event_with_maintenance_fact() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)
    aggregate.clear_pending_events()

    result = aggregate.submit_loading_photos(_submit_loading_photos_command(submitted_at=_T1))

    assert isinstance(result, PhotosSubmitted)
    events = aggregate.collect_events()
    assert events == [result]
    assert result.maintenance_completed_at == _T1
    assert result.technician_id == _TECH_A
    caps = _capabilities(aggregate, _TECH_A, checked_at=_T1)
    assert caps.maintenance_completed_today is True


def test_submit_loading_photos_after_existing_maintenance_has_no_embedded_fact() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)
    completed = aggregate.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH_A, completed_at=_T0),
    )
    assert isinstance(completed, MaintenanceCompleted)
    aggregate.clear_pending_events()

    result = aggregate.submit_loading_photos(
        _submit_loading_photos_command(submitted_at=_T1, batch_id=_BATCH_ID_2),
    )

    assert isinstance(result, PhotosSubmitted)
    assert result.maintenance_completed_at is None
    assert len(aggregate.collect_events()) == 1
    assert not any(isinstance(e, MaintenanceCompleted) for e in aggregate.collect_events())


def test_composite_photo_event_rehydrate_matches_live_maintenance_state() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)
    seed_events = list(aggregate.collect_events())
    assert any(isinstance(event, LoadingSubmitted) for event in seed_events)
    assert any(isinstance(event, RevisionCompleted) for event in seed_events)
    aggregate.clear_pending_events()

    photo_event = aggregate.submit_loading_photos(
        _submit_loading_photos_command(submitted_at=_T1),
    )
    assert isinstance(photo_event, PhotosSubmitted)
    assert photo_event.maintenance_completed_at == _T1

    replayed = MachineOperations.rehydrate(_MACHINE_ID, [*seed_events, photo_event])
    assert _capabilities(replayed, _TECH_A, checked_at=_T1).maintenance_completed_today


def test_submit_loading_photos_rejected_in_onboarding() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)

    result = aggregate.submit_loading_photos(_submit_loading_photos_command())

    assert isinstance(result, LoadingPhotosNotAllowed)
    assert result.reason == LOADING_PHOTOS_NOT_ALLOWED_REASON
    assert aggregate.collect_events() == []


def test_submit_loading_photos_rejected_without_loading_when_responsible() -> None:
    # ISS-018: фото остаются gated по loading_completed (в отличие от complete ТО)
    aggregate = MachineOperations.rehydrate(
        _MACHINE_ID,
        [
            RevisionCompleted(
                event_id=EventId("event-rev-1"),
                revision_id=RevisionId("rev-1"),
                technician_id=_TECH_A,
                machine_id=_MACHINE_ID,
                completed_at=_T0,
                occurred_at=_T0,
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-revision",
                form_token="token-rev-1",
            ),
        ],
    )
    assert _capabilities(aggregate, _TECH_A).loading_completed is False
    assert _capabilities(aggregate, _TECH_A).can_complete_maintenance is True

    result = aggregate.submit_loading_photos(_submit_loading_photos_command())

    assert isinstance(result, LoadingPhotosNotAllowed)
    assert result.reason == LOADING_PHOTOS_REQUIRE_LOADING_REASON


def test_submit_loading_photos_rejected_for_other_technician() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, technician_id=_TECH_A)

    result = aggregate.submit_loading_photos(
        _submit_loading_photos_command(technician_id=_TECH_B),
    )

    assert isinstance(result, LoadingPhotosNotAllowed)


def test_submit_loading_photos_rejected_before_revision_timestamp() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, completed_at=_T1)

    result = aggregate.submit_loading_photos(
        _submit_loading_photos_command(submitted_at=_T0),
    )

    assert isinstance(result, LoadingPhotosNotAllowed)


def test_submit_loading_photos_insufficient_count() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)

    result = aggregate.submit_loading_photos(
        _submit_loading_photos_command(
            photos=(_PHOTO,),
            min_photo_count=2,
        ),
    )

    assert isinstance(result, LoadingPhotosInsufficientCount)
    assert result.reason == LOADING_PHOTOS_INSUFFICIENT_COUNT_REASON
    assert result.min_photo_count == 2
    assert result.actual_count == 1


def test_submit_loading_photos_idempotent_by_batch_id() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)

    first = aggregate.submit_loading_photos(_submit_loading_photos_command())
    aggregate.clear_pending_events()
    second = aggregate.submit_loading_photos(_submit_loading_photos_command())

    assert isinstance(first, PhotosSubmitted)
    assert second is first
    assert aggregate.collect_events() == []
    caps = _capabilities(aggregate, _TECH_A, checked_at=_T1)
    assert caps.maintenance_completed_today is True


def test_rehydrate_restores_photos_and_capabilities() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)
    revision_events = aggregate.collect_events()
    submitted = aggregate.submit_loading_photos(_submit_loading_photos_command())
    assert isinstance(submitted, PhotosSubmitted)
    photo_events = aggregate.collect_events()

    restored = MachineOperations.rehydrate(
        _MACHINE_ID,
        [*revision_events, *photo_events],
    )
    caps = _capabilities(restored, _TECH_A, checked_at=_T1)

    assert caps.loading_photos_completed is True
    assert caps.can_submit_loading_photos is False


def test_capabilities_before_and_after_photos() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)

    before = _capabilities(aggregate, _TECH_A, checked_at=_T1)
    assert before.can_submit_loading_photos is True
    assert before.loading_photos_completed is False

    aggregate.submit_loading_photos(_submit_loading_photos_command())
    after = _capabilities(aggregate, _TECH_A, checked_at=_T1)
    assert after.loading_photos_completed is True
    assert after.can_submit_loading_photos is False


def test_onboarding_capabilities_disable_loading_photos() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    caps = _capabilities(aggregate, _TECH_A)

    assert caps.can_submit_loading_photos is False
    assert caps.loading_photos_completed is False


def test_submit_loading_photos_command_rejects_invalid_min_count() -> None:
    with pytest.raises(ValueError, match="min_photo_count must be at least 1"):
        SubmitLoadingPhotos(
            technician_id=_TECH_A,
            batch_id=_BATCH_ID,
            submitted_at=_T1,
            photos=(_PHOTO,),
            min_photo_count=0,
        )


def test_photos_submitted_after_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate, completed_at=_T0)

    result = aggregate.submit_loading_photos(
        _submit_loading_photos_command(submitted_at=_T1),
    )
    assert isinstance(result, PhotosSubmitted)


def test_submit_loading_photos_rejected_when_already_submitted_today() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)

    first = aggregate.submit_loading_photos(_submit_loading_photos_command())
    aggregate.clear_pending_events()
    second = aggregate.submit_loading_photos(
        _submit_loading_photos_command(
            batch_id=_BATCH_ID_2,
            submitted_at=_T2,
        ),
    )

    assert isinstance(first, PhotosSubmitted)
    assert isinstance(second, LoadingPhotosAlreadySubmittedToday)
    assert second.reason == LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON
    assert aggregate.collect_events() == []


def test_capabilities_photos_yesterday_not_completed_today() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)
    aggregate.submit_loading_photos(
        _submit_loading_photos_command(submitted_at=_T1),
    )
    next_load = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH_A,
            submitted_at=_T_NEXT_DAY,
            form_id="form-loading",
            form_token="token-load-next-day",
        ),
    )
    assert isinstance(next_load, LoadingSubmitted)

    caps = _capabilities(aggregate, _TECH_A, checked_at=_T_NEXT_DAY)

    assert caps.loading_photos_completed is False
    assert caps.can_submit_loading_photos is True


def test_submit_loading_photos_allowed_on_next_calendar_day() -> None:
    aggregate = MachineOperations.empty(_MACHINE_ID)
    _complete_revision(aggregate)

    first = aggregate.submit_loading_photos(
        _submit_loading_photos_command(submitted_at=_T1),
    )
    aggregate.clear_pending_events()
    next_load = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH_A,
            submitted_at=_T_NEXT_DAY,
            form_id="form-loading",
            form_token="token-load-next-day",
        ),
    )
    assert isinstance(next_load, LoadingSubmitted)
    second = aggregate.submit_loading_photos(
        _submit_loading_photos_command(
            batch_id=_BATCH_ID_2,
            submitted_at=_T_NEXT_DAY,
        ),
    )

    assert isinstance(first, PhotosSubmitted)
    assert isinstance(second, PhotosSubmitted)
    assert second.batch_id == _BATCH_ID_2
    assert second.maintenance_completed_at == _T_NEXT_DAY
    assert len(aggregate.collect_events()) == 2
