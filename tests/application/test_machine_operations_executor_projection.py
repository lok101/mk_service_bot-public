from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.machine_operations.executor import MachineOperationsExecutor
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.machine_operations import (
    CompleteMaintenance,
    CompleteRevision,
    LoadingSubmitted,
    SubmitLoading,
    SubmitLoadingPhotos,
)
from src.domain.machine_operations.events import MaintenanceCompleted
from src.domain.models import RevisionSource
from src.domain.photo_batch import PhotoRef
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore

_MACHINE = MachineId("vm-01")
_MACHINE_PHOTO = MachineId("vm-photo")
_TECH = TechnicianId("tech-a")
_T_REV = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
_T_MC = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
_T_PHOTO = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
_BATCH_ID = BatchId("batch-01")
_PHOTO_1 = PhotoRef(file_id="f1", file_unique_id="u1", message_id=1)
_PHOTO_2 = PhotoRef(file_id="f2", file_unique_id="u2", message_id=2)


def _seed_revision(
    executor: MachineOperationsExecutor,
    machine_id: MachineId,
    *,
    form_token: str,
) -> None:
    loading = executor.execute(
        machine_id,
        lambda agg: agg.submit_loading(
            SubmitLoading(
                technician_id=_TECH,
                submitted_at=_T_REV - timedelta(minutes=1),
                form_id="form-loading",
                form_token=f"load-before-{form_token}",
            ),
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    executor.execute(
        machine_id,
        lambda agg: agg.complete_revision(
            CompleteRevision(
                technician_id=_TECH,
                completed_at=_T_REV,
                source=RevisionSource.GOOGLE_FORM,
                form_id="f",
                form_token=form_token,
            ),
        ),
    )


def test_executor_upserts_technician_last_maintenance_after_maintenance_completed() -> None:
    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    projection = InMemoryTechnicianLastMaintenanceProjection()
    executor = MachineOperationsExecutor(
        repository=repository,
        technician_last_maintenance=projection,
    )
    _seed_revision(executor, _MACHINE, form_token="t")
    result = executor.execute(
        _MACHINE,
        lambda agg: agg.complete_maintenance(
            CompleteMaintenance(technician_id=_TECH, completed_at=_T_MC),
            checked_at=_T_MC,
        ),
    )
    assert isinstance(result, MaintenanceCompleted)
    snapshot = projection.get_last(_TECH)
    assert snapshot == TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=_T_MC,
    )


def test_executor_upserts_after_single_composite_photo_event() -> None:
    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    projection = InMemoryTechnicianLastMaintenanceProjection()
    executor = MachineOperationsExecutor(
        repository=repository,
        technician_last_maintenance=projection,
    )
    _seed_revision(executor, _MACHINE_PHOTO, form_token="t-photo")
    result = executor.execute(
        _MACHINE_PHOTO,
        lambda agg: agg.submit_loading_photos(
            SubmitLoadingPhotos(
                technician_id=_TECH,
                batch_id=_BATCH_ID,
                submitted_at=_T_PHOTO,
                photos=(_PHOTO_1, _PHOTO_2),
                min_photo_count=2,
            ),
        ),
    )
    from src.domain.machine_operations.events import PhotosSubmitted

    assert isinstance(result, PhotosSubmitted)
    assert result.maintenance_completed_at == _T_PHOTO
    snapshot = projection.get_last(_TECH)
    assert snapshot == TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE_PHOTO,
        completed_at=_T_PHOTO,
    )
