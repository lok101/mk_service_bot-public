from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import RegisterLoadingPhotosService
from src.application.machine_operations.use_cases import (
    LoadingPhotosBlocked,
    SubmitLoadingPhotosCommand,
)
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.machine_operations import (
    CompleteMaintenance,
    CompleteRevision,
    LoadingSubmitted,
    SubmitLoading,
)
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot
from src.domain.models import RevisionSource
from src.domain.photo_batch import PhotoRef
from src.domain.results import MaintenanceCooldownActive
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore

_MACHINE_ID = MachineId("vm-01")
_OTHER_MACHINE = MachineId("vm-other")
_TECH = TechnicianId("tech-a")
_TECH_OTHER = TechnicianId("tech-other")
_T_REV = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
_T_MAINT_OTHER = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
_T_SUBMIT = datetime(2026, 7, 2, 10, 5, tzinfo=UTC)
_T_MAINT_TODAY = datetime(2026, 7, 2, 9, 30, tzinfo=UTC)
_BATCH_ID = BatchId("batch-01")
_PHOTO_1 = PhotoRef(file_id="f1", file_unique_id="u1", message_id=1)
_PHOTO_2 = PhotoRef(file_id="f2", file_unique_id="u2", message_id=2)
_MSK = ZoneInfo("Europe/Moscow")
_OPEN_BLOCK = "Сначала пересчёт микромаркета."


class _PhotoGate:
    def __init__(
        self,
        *,
        block: str | None = None,
        close_error: BaseException | None = None,
        suppress: bool = False,
        inventory_block: str | None = None,
    ) -> None:
        self.block = block
        self.close_error = close_error
        self.suppress = suppress
        self.inventory_block = inventory_block
        self.closed = 0

    def complete_maintenance_block_reason(
        self,
        machine_id: object,
        checked_at: object,
    ) -> str | None:
        del machine_id, checked_at
        return self.inventory_block

    def suppress_coffee_revision(self, machine_id: object) -> bool:
        del machine_id
        return self.suppress

    def loading_photos_block_reason(self, machine_id: object, checked_at: object) -> str | None:
        del machine_id, checked_at
        return self.block

    def close_loading_order_after_visit_final(self, machine_id: object) -> None:
        del machine_id
        if self.close_error is not None:
            raise self.close_error
        self.closed += 1


class _FakeBypassReader:
    def __init__(self, snapshot: MaintenanceCooldownBypassSnapshot | None) -> None:
        self._snapshot = snapshot

    def get_active(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> MaintenanceCooldownBypassSnapshot | None:
        _ = checked_at
        return self._snapshot


_BYPASS = _FakeBypassReader(
    MaintenanceCooldownBypassSnapshot(
        service_date=date(2026, 7, 2),
        activated_at=_T_SUBMIT,
    ),
)


def _build_service(
    *,
    cooldown_minutes: int = 20,
    bypass_reader: object | None = None,
    service_calendar_timezone: ZoneInfo = _MSK,
    inventory_gate: object | None = None,
) -> tuple[
    RegisterLoadingPhotosService,
    EventSourcedMachineOperationsRepository,
    InMemoryTechnicianLastMaintenanceProjection,
]:
    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    projection = InMemoryTechnicianLastMaintenanceProjection()
    executor = MachineOperationsExecutor(repository=repository)
    service = RegisterLoadingPhotosService(
        executor=executor,
        machine_operations=repository,
        last_maintenance_reader=projection,
        maintenance_cooldown_minutes=cooldown_minutes,
        bypass_reader=bypass_reader,
        service_calendar_timezone=service_calendar_timezone,
        inventory_gate=inventory_gate,  # type: ignore[arg-type]
    )
    return service, repository, projection


def _seed_revision(repository: EventSourcedMachineOperationsRepository) -> None:
    aggregate = repository.get(_MACHINE_ID)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH,
            submitted_at=_T_REV - timedelta(minutes=1),
            form_id="form-loading",
            form_token="load-before-token-rev",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)
    aggregate = repository.get(_MACHINE_ID)
    aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH,
            completed_at=_T_REV,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-rev",
            form_token="token-rev",
        ),
    )
    repository.save(aggregate)


def _photos_command(*, batch_id: BatchId = _BATCH_ID) -> SubmitLoadingPhotosCommand:
    return SubmitLoadingPhotosCommand(
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        batch_id=batch_id,
        submitted_at=_T_SUBMIT,
        photos=(_PHOTO_1, _PHOTO_2),
        min_photo_count=2,
    )


def test_register_loading_photos_returns_cooldown_active() -> None:
    service, repository, projection = _build_service()
    _seed_revision(repository)
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_OTHER_MACHINE,
            completed_at=_T_MAINT_OTHER,
        ),
    )

    result = service.execute(_photos_command())

    assert isinstance(result, MaintenanceCooldownActive)
    reloaded = repository.get(_MACHINE_ID)
    # Seed loading remains; cooldown blocked photos (no new aggregate mutation).
    assert reloaded.last_loading_submitted_at() == _T_REV - timedelta(minutes=1)


def test_register_loading_photos_succeeds_when_bypass_active() -> None:
    service, repository, projection = _build_service(bypass_reader=_BYPASS)
    _seed_revision(repository)
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_OTHER_MACHINE,
            completed_at=_T_MAINT_OTHER,
        ),
    )

    result = service.execute(_photos_command())

    assert isinstance(result, PhotosSubmitted)


def test_register_loading_photos_allowed_when_maintenance_completed_today() -> None:
    service, repository, projection = _build_service()
    _seed_revision(repository)
    aggregate = repository.get(_MACHINE_ID)
    aggregate.complete_maintenance(
        CompleteMaintenance(technician_id=_TECH, completed_at=_T_MAINT_TODAY),
        checked_at=_T_MAINT_TODAY,
    )
    repository.save(aggregate)
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_OTHER_MACHINE,
            completed_at=_T_MAINT_OTHER,
        ),
    )

    result = service.execute(_photos_command())

    assert isinstance(result, PhotosSubmitted)


def test_register_loading_photos_succeeds_awaiting_handover_when_bypass_active() -> None:
    service, repository, _projection = _build_service(bypass_reader=_BYPASS)
    _seed_revision(repository)
    # Coffee phase: bypass skips hold, but acting technician still needs loading.
    aggregate = repository.get(_MACHINE_ID)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH_OTHER,
            submitted_at=_T_SUBMIT - timedelta(minutes=1),
            form_id="form-loading",
            form_token="load-before-batch-fm-1",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)
    result = service.execute(
        SubmitLoadingPhotosCommand(
            technician_id=_TECH_OTHER,
            machine_id=_MACHINE_ID,
            batch_id=BatchId("batch-fm-1"),
            submitted_at=_T_SUBMIT,
            photos=(_PHOTO_1, _PHOTO_2),
            min_photo_count=2,
        ),
    )
    assert isinstance(result, PhotosSubmitted)


def test_photos_rejected_while_order_open() -> None:
    # error: open order blocks loading photos
    gate = _PhotoGate(block=_OPEN_BLOCK)
    service, repository, _projection = _build_service(
        bypass_reader=_BYPASS,
        inventory_gate=gate,
    )
    _seed_revision(repository)

    result = service.execute(_photos_command())

    assert isinstance(result, LoadingPhotosBlocked)
    assert result.reason == _OPEN_BLOCK
    assert repository.get(_MACHINE_ID).last_loading_submitted_at() == (
        _T_REV - timedelta(minutes=1)
    )
    assert gate.closed == 0


def test_photos_close_recounted_order() -> None:
    # happy: recounted order closes after photos
    gate = _PhotoGate(block=None)
    service, repository, _projection = _build_service(
        bypass_reader=_BYPASS,
        inventory_gate=gate,
    )
    _seed_revision(repository)

    result = service.execute(_photos_command())

    assert isinstance(result, PhotosSubmitted)
    assert gate.closed == 1


def test_photo_success_survives_failed_order_close() -> None:
    # error path for close: photos still succeed
    gate = _PhotoGate(close_error=RuntimeError("close failed"))
    service, repository, _projection = _build_service(
        bypass_reader=_BYPASS,
        inventory_gate=gate,
    )
    _seed_revision(repository)

    result = service.execute(_photos_command())

    assert isinstance(result, PhotosSubmitted)
    assert gate.closed == 0


def test_register_loading_photos_suppress_without_revision_writes_and_closes() -> None:
    # happy: suppress, нет ревизии, order не блокирует → PhotosSubmitted + close
    gate = _PhotoGate(block=None, suppress=True, inventory_block=None)
    service, repository, _projection = _build_service(
        bypass_reader=_BYPASS,
        inventory_gate=gate,
        cooldown_minutes=0,
    )
    # ревизию НЕ сидим
    result = service.execute(_photos_command())
    assert isinstance(result, PhotosSubmitted)
    assert result.maintenance_completed_at is not None
    assert gate.closed == 1


def test_register_loading_photos_suppress_inventory_blocks_write() -> None:
    # edge: inventory block при suppress → LoadingPhotosBlocked, close=0
    from src.application.micromarket_loading.complete_maintenance_gate import (
        MICROMARKET_INVENTORY_REQUIRED_REASON,
    )

    gate = _PhotoGate(
        block=None,
        suppress=True,
        inventory_block=MICROMARKET_INVENTORY_REQUIRED_REASON,
    )
    service, repository, _projection = _build_service(
        cooldown_minutes=0,
        inventory_gate=gate,
    )
    result = service.execute(_photos_command())
    assert isinstance(result, LoadingPhotosBlocked)
    assert result.reason == MICROMARKET_INVENTORY_REQUIRED_REASON
    assert gate.closed == 0
    assert repository.get(_MACHINE_ID).last_loading_submitted_at() is None


def test_register_loading_photos_without_suppress_still_needs_revision() -> None:
    # error: gate.suppress=False, без ревизии → LoadingPhotosNotAllowed
    from src.domain.results import LoadingPhotosNotAllowed

    gate = _PhotoGate(block=None, suppress=False)
    service, repository, _projection = _build_service(
        bypass_reader=_BYPASS,
        inventory_gate=gate,
        cooldown_minutes=0,
    )
    result = service.execute(_photos_command())
    assert isinstance(result, LoadingPhotosNotAllowed)
    assert gate.closed == 0
