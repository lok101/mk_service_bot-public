from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.machine_operations import (
    CompleteMaintenance,
    MachineOperations,
    MaintenanceCompleted,
    PhotosSubmitted,
    SubmitLoadingPhotos,
)
from src.domain.photo_batch import PhotoRef
from src.domain.results import (
    LoadingPhotosNotAllowed,
    MaintenanceNotAllowed,
)

_MACHINE = MachineId("701")
_TECH = TechnicianId("tech-mm")
_CHECKED = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
_MSK = ZoneInfo("Europe/Moscow")
_BATCH = BatchId("batch-mm-1")
_PHOTO_1 = PhotoRef(file_id="f1", file_unique_id="u1", message_id=1)
_PHOTO_2 = PhotoRef(file_id="f2", file_unique_id="u2", message_id=2)


def test_allow_missing_revision_form_opens_visit_without_coffee_loading() -> None:
    aggregate = MachineOperations.empty(_MACHINE, service_calendar_timezone=_MSK)
    caps = aggregate.get_service_capabilities(
        _TECH,
        checked_at=_CHECKED,
        allow_missing_revision_form=True,
    )
    assert caps.responsibility_phase == "awaiting_handover"
    assert caps.can_complete_revision is False
    assert caps.revision_form_link is None
    assert caps.can_submit_loading is False
    assert caps.can_complete_maintenance is True
    assert caps.can_submit_loading_photos is True


def test_awaiting_handover_without_link_still_requires_revision_form() -> None:
    aggregate = MachineOperations.empty(_MACHINE)
    with pytest.raises(ValueError, match="revision_form_link is required"):
        aggregate.get_service_capabilities(_TECH, checked_at=_CHECKED)


def test_complete_maintenance_allow_missing_revision_writes_event() -> None:
    aggregate = MachineOperations.empty(_MACHINE, service_calendar_timezone=_MSK)
    result = aggregate.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=_CHECKED),
        checked_at=_CHECKED,
        allow_missing_revision=True,
    )
    assert isinstance(result, MaintenanceCompleted)
    assert aggregate.last_maintenance_completed_at() == _CHECKED


def test_complete_maintenance_without_allow_rejects_without_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE, service_calendar_timezone=_MSK)
    result = aggregate.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=_CHECKED),
        checked_at=_CHECKED,
    )
    assert isinstance(result, MaintenanceNotAllowed)


def test_submit_loading_photos_allow_missing_revision_without_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE, service_calendar_timezone=_MSK)
    result = aggregate.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH,
            batch_id=_BATCH,
            submitted_at=_CHECKED,
            photos=(_PHOTO_1, _PHOTO_2),
            min_photo_count=2,
        ),
        allow_missing_revision=True,
    )
    assert isinstance(result, PhotosSubmitted)
    assert result.maintenance_completed_at == _CHECKED


def test_skip_responsibility_alone_does_not_bypass_missing_revision() -> None:
    aggregate = MachineOperations.empty(_MACHINE, service_calendar_timezone=_MSK)
    result = aggregate.submit_loading_photos(
        SubmitLoadingPhotos(
            technician_id=_TECH,
            batch_id=BatchId("batch-skip-only"),
            submitted_at=_CHECKED,
            photos=(_PHOTO_1, _PHOTO_2),
            min_photo_count=2,
        ),
        skip_responsibility_check=True,
    )
    assert isinstance(result, LoadingPhotosNotAllowed)


def test_rehydrate_matches_complete_maintenance_allow_missing_revision() -> None:
    command_path = MachineOperations.empty(_MACHINE, service_calendar_timezone=_MSK)
    result = command_path.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=_CHECKED),
        checked_at=_CHECKED,
        allow_missing_revision=True,
    )
    assert isinstance(result, MaintenanceCompleted)
    events = list(command_path.collect_events())

    replayed = MachineOperations.rehydrate(
        _MACHINE,
        events,
        service_calendar_timezone=_MSK,
    )
    assert replayed.last_maintenance_completed_at() == command_path.last_maintenance_completed_at()
    caps_cmd = command_path.get_service_capabilities(
        _TECH,
        checked_at=_CHECKED,
        allow_missing_revision_form=True,
    )
    caps_rep = replayed.get_service_capabilities(
        _TECH,
        checked_at=_CHECKED,
        allow_missing_revision_form=True,
    )
    assert caps_rep.can_complete_maintenance == caps_cmd.can_complete_maintenance
    assert caps_rep.maintenance_completed_today == caps_cmd.maintenance_completed_today
