from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.domain.calendar import calendar_anchor
from src.domain.ids import BatchId, MachineId, TechnicianId
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
    LoadingPhotosAlreadySubmittedToday,
    LoadingPhotosNotAllowed,
    MaintenanceAlreadyCompletedToday,
    MaintenanceNotAllowed,
)

_MACHINE = MachineId("vm-skip")
_TECH_A = TechnicianId("tech-a")
_TECH_B = TechnicianId("tech-b")
_T_REV = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_T_DONE = datetime(2026, 7, 2, 18, 0, tzinfo=UTC)
_BATCH = BatchId("batch-skip-1")
_PHOTO_1 = PhotoRef(file_id="f1", file_unique_id="u1", message_id=1)
_PHOTO_2 = PhotoRef(file_id="f2", file_unique_id="u2", message_id=2)
_MSK = ZoneInfo("Europe/Moscow")
_LINK = PrefilledFormLink(url="https://example.com/revision")


def _complete_revision(
    aggregate: MachineOperations,
    *,
    technician_id: TechnicianId = _TECH_A,
    completed_at: datetime = _T_REV,
    form_token: str = "token-rev-a",
) -> RevisionCompleted:
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=technician_id,
            submitted_at=completed_at - timedelta(minutes=1),
            form_id="form-loading",
            form_token=f"load-before-{form_token}",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=technician_id,
            completed_at=completed_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-rev",
            form_token=form_token,
        ),
    )
    assert isinstance(result, RevisionCompleted)
    return result


def _aggregate_with_revision_by_a() -> MachineOperations:
    aggregate = MachineOperations.empty(_MACHINE)
    _complete_revision(aggregate)
    return aggregate


def test_complete_maintenance_without_skip_rejects_without_hold() -> None:
    aggregate = _aggregate_with_revision_by_a()
    result = aggregate.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH_B, completed_at=_T_DONE),
        checked_at=_T_DONE,
    )
    assert isinstance(result, MaintenanceNotAllowed)


def _submit_loading_for(
    aggregate: MachineOperations,
    technician_id: TechnicianId,
    *,
    submitted_at: datetime,
    form_token: str,
) -> None:
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=technician_id,
            submitted_at=submitted_at,
            form_id="form-loading",
            form_token=form_token,
        ),
    )
    assert isinstance(loading, LoadingSubmitted)


def test_complete_maintenance_skip_allows_without_hold() -> None:
    aggregate = _aggregate_with_revision_by_a()
    # Coffee phase: skip hold still requires loading for the acting technician.
    _submit_loading_for(
        aggregate,
        _TECH_B,
        submitted_at=_T_DONE - timedelta(minutes=1),
        form_token="load-tech-b-maint",
    )
    result = aggregate.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH_B, completed_at=_T_DONE),
        checked_at=_T_DONE,
        skip_responsibility_check=True,
    )
    assert isinstance(result, MaintenanceCompleted)


def test_submit_loading_photos_without_skip_rejects_without_hold() -> None:
    aggregate = _aggregate_with_revision_by_a()
    _submit_loading_for(
        aggregate,
        _TECH_B,
        submitted_at=_T_DONE - timedelta(minutes=1),
        form_token="load-tech-b-photos-reject",
    )
    result = aggregate.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH_B,
            batch_id=_BATCH,
            submitted_at=_T_DONE,
            photos=(_PHOTO_1, _PHOTO_2),
            min_photo_count=2,
        ),
    )
    assert isinstance(result, LoadingPhotosNotAllowed)


def test_submit_loading_photos_skip_allows_without_hold() -> None:
    aggregate = _aggregate_with_revision_by_a()
    _submit_loading_for(
        aggregate,
        _TECH_B,
        submitted_at=_T_DONE - timedelta(minutes=1),
        form_token="load-tech-b-photos",
    )
    result = aggregate.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH_B,
            batch_id=_BATCH,
            submitted_at=_T_DONE,
            photos=(_PHOTO_1, _PHOTO_2),
            min_photo_count=2,
        ),
        skip_responsibility_check=True,
    )
    assert isinstance(result, PhotosSubmitted)


def test_submit_loading_photos_skip_still_rejects_without_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE)
    result = aggregate.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH_B,
            batch_id=BatchId("batch-empty"),
            submitted_at=_T_DONE,
            photos=(_PHOTO_1, _PHOTO_2),
            min_photo_count=2,
        ),
        skip_responsibility_check=True,
    )
    assert isinstance(result, LoadingPhotosNotAllowed)


def test_get_service_capabilities_skip_builds_force_majeure_effective_caps() -> None:
    aggregate = MachineOperations.empty(
        _MACHINE,
        service_calendar_timezone=_MSK,
    )
    _complete_revision(aggregate, form_token="token-rev-caps")

    caps = aggregate.get_service_capabilities(
        _TECH_B,
        checked_at=_T_DONE,
        revision_form_link=_LINK,
        skip_responsibility_check=True,
    )
    assert caps.responsibility_phase == "responsible"
    # Coffee phase: skip opens effective responsible; revision/photos need own loading.
    assert caps.can_complete_revision is False
    assert caps.revision_form_link is None
    assert caps.revision_due_status is None
    assert caps.responsibility_expires_at == calendar_anchor(_T_DONE, _MSK)
    assert caps.can_submit_loading is True
    # ISS-018: complete без loading; фото остаются gated
    assert caps.can_complete_maintenance is True
    assert caps.can_submit_loading_photos is False


def test_get_service_capabilities_skip_allows_missing_revision_form() -> None:
    aggregate = MachineOperations.empty(
        _MACHINE,
        service_calendar_timezone=_MSK,
    )
    caps = aggregate.get_service_capabilities(
        _TECH_B,
        checked_at=_T_DONE,
        skip_responsibility_check=True,
        allow_missing_revision_form=True,
    )
    assert caps.responsibility_phase == "responsible"
    assert caps.can_complete_revision is False
    assert caps.revision_form_link is None
    assert caps.can_submit_loading is False
    assert caps.can_submit_loading_photos is True
    assert caps.can_complete_maintenance is True


def test_get_service_capabilities_skip_without_revision_disables_photos() -> None:
    aggregate = MachineOperations.empty(
        _MACHINE,
        service_calendar_timezone=_MSK,
    )
    caps = aggregate.get_service_capabilities(
        _TECH_B,
        checked_at=_T_DONE,
        revision_form_link=_LINK,
        skip_responsibility_check=True,
    )
    assert caps.responsibility_phase == "responsible"
    assert caps.can_complete_revision is False
    assert caps.can_submit_loading is True
    assert caps.can_submit_loading_photos is False
    assert caps.can_complete_maintenance is True


def test_complete_maintenance_skip_still_rejects_day_limit() -> None:
    aggregate = _aggregate_with_revision_by_a()
    _submit_loading_for(
        aggregate,
        _TECH_B,
        submitted_at=_T_DONE - timedelta(minutes=1),
        form_token="load-tech-b-day-limit",
    )
    first = aggregate.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH_B, completed_at=_T_DONE),
        checked_at=_T_DONE,
        skip_responsibility_check=True,
    )
    assert isinstance(first, MaintenanceCompleted)

    second = aggregate.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH_B, completed_at=_T_DONE),
        checked_at=_T_DONE,
        skip_responsibility_check=True,
    )
    assert isinstance(second, MaintenanceAlreadyCompletedToday)


def test_submit_loading_photos_skip_still_rejects_day_limit() -> None:
    aggregate = _aggregate_with_revision_by_a()
    _submit_loading_for(
        aggregate,
        _TECH_B,
        submitted_at=_T_DONE - timedelta(minutes=1),
        form_token="load-tech-b-photos-day",
    )
    first = aggregate.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH_B,
            batch_id=_BATCH,
            submitted_at=_T_DONE,
            photos=(_PHOTO_1, _PHOTO_2),
            min_photo_count=2,
        ),
        skip_responsibility_check=True,
    )
    assert isinstance(first, PhotosSubmitted)

    second = aggregate.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH_B,
            batch_id=BatchId("batch-skip-2"),
            submitted_at=_T_DONE,
            photos=(_PHOTO_1, _PHOTO_2),
            min_photo_count=2,
        ),
        skip_responsibility_check=True,
    )
    assert isinstance(second, LoadingPhotosAlreadySubmittedToday)
