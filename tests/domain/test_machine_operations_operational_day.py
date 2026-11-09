from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
from src.domain.models import RevisionSource
from src.domain.photo_batch import PhotoRef
from src.domain.results import MaintenanceAlreadyCompletedToday

_TZ = ZoneInfo("Asia/Yekaterinburg")
_MACHINE = MachineId("vm-01")
_TECH = TechnicianId("tech-a")
_REVISION_AT = datetime(2026, 8, 10, 10, 0, tzinfo=_TZ)


def _complete_revision(aggregate: MachineOperations) -> RevisionCompleted:
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH,
            submitted_at=_REVISION_AT - timedelta(minutes=1),
            form_id="form-loading",
            form_token="load-before-token-rev-1",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH,
            completed_at=_REVISION_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert isinstance(result, RevisionCompleted)
    return result


def _ops() -> MachineOperations:
    aggregate = MachineOperations.empty(
        _MACHINE,
        service_calendar_timezone=_TZ,
        service_day_end_hour=6,
    )
    _complete_revision(aggregate)
    aggregate.clear_pending_events()
    return aggregate


def test_maintenance_at_0559_counts_as_previous_operational_day() -> None:
    ops = _ops()
    first_at = datetime(2026, 8, 12, 5, 59, tzinfo=_TZ)
    second_at = datetime(2026, 8, 12, 6, 0, tzinfo=_TZ)
    first = ops.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=first_at),
        checked_at=first_at,
    )
    assert isinstance(first, MaintenanceCompleted)
    second = ops.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=second_at),
        checked_at=second_at,
    )
    assert isinstance(second, MaintenanceCompleted)


def test_second_maintenance_same_operational_day_rejected_without_flag() -> None:
    ops = _ops()
    at = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)
    first = ops.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=at),
        checked_at=at,
    )
    assert isinstance(first, MaintenanceCompleted)
    second = ops.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=at),
        checked_at=at,
    )
    assert isinstance(second, MaintenanceAlreadyCompletedToday)


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


def test_second_maintenance_same_operational_day_allowed_with_flag() -> None:
    ops = _ops()
    at = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)
    first = ops.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=at),
        checked_at=at,
    )
    assert isinstance(first, MaintenanceCompleted)
    second = ops.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=at),
        checked_at=at,
        allow_additional_maintenance=True,
    )
    assert isinstance(second, MaintenanceCompleted)
    assert second.event_id != first.event_id


def test_second_photos_with_extra_flag_records_second_maintenance() -> None:
    ops = MachineOperations.empty(
        _MACHINE,
        service_calendar_timezone=_TZ,
        service_day_end_hour=6,
    )
    _complete_revision(ops)
    at = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)
    same_day_loading = ops.submit_loading(
        SubmitLoading(
            technician_id=_TECH,
            submitted_at=at - timedelta(minutes=5),
            form_id="form-loading",
            form_token="load-same-day-photos",
        ),
    )
    assert isinstance(same_day_loading, LoadingSubmitted)
    first_photos = ops.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH,
            batch_id=BatchId("batch-1"),
            submitted_at=at,
            photos=(_PHOTO, _PHOTO_2),
            min_photo_count=2,
        ),
    )
    assert isinstance(first_photos, PhotosSubmitted)
    second_photos = ops.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH,
            batch_id=BatchId("batch-2"),
            submitted_at=at,
            photos=(_PHOTO, _PHOTO_2),
            min_photo_count=2,
        ),
        allow_additional_maintenance=True,
    )
    assert isinstance(second_photos, PhotosSubmitted)
    pending = ops.collect_events()
    assert not any(isinstance(event, MaintenanceCompleted) for event in pending)
    photo_events = [event for event in pending if isinstance(event, PhotosSubmitted)]
    assert len(photo_events) == 2
    assert all(event.maintenance_completed_at == at for event in photo_events)

    replayed = MachineOperations.rehydrate(
        _MACHINE,
        list(pending),
        service_calendar_timezone=_TZ,
        service_day_end_hour=6,
    )
    assert replayed.last_maintenance_completed_at() == at
    assert (
        replayed.get_service_capabilities(_TECH, checked_at=at).maintenance_completed_today is True
    )
