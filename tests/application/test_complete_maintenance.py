from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import CompleteMaintenanceService
from src.application.machine_operations.use_cases import CompleteMaintenanceCommand
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations import (
    CompleteRevision,
    LoadingSubmitted,
    RevisionCompleted,
    SubmitLoading,
)
from src.domain.machine_operations.events import MaintenanceCompleted
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot
from src.domain.models import RevisionSource
from src.domain.results import (
    MaintenanceAlreadyCompletedToday,
    MaintenanceCooldownActive,
    MaintenanceNotAllowed,
)
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore

_MACHINE_ID = MachineId("vm-01")
_TECH_A = TechnicianId("tech-a")
_TECH_OTHER = TechnicianId("tech-other")
_MSK = ZoneInfo("Europe/Moscow")


def _seed_revision(repository: EventSourcedMachineOperationsRepository) -> None:
    completed_at = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    aggregate = repository.get(_MACHINE_ID)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH_A,
            submitted_at=completed_at - timedelta(minutes=1),
            form_id="form-loading",
            form_token="load-before-token-rev-1",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)
    aggregate = repository.get(_MACHINE_ID)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH_A,
            completed_at=completed_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert isinstance(result, RevisionCompleted)
    repository.save(aggregate)


def _complete_service(
    repository: EventSourcedMachineOperationsRepository,
    *,
    projection: InMemoryTechnicianLastMaintenanceProjection | None = None,
    cooldown_minutes: int = 0,
    bypass_reader: object | None = None,
    service_calendar_timezone: ZoneInfo = _MSK,
    inventory_gate: object | None = None,
) -> CompleteMaintenanceService:
    reader = projection or InMemoryTechnicianLastMaintenanceProjection()
    return CompleteMaintenanceService(
        executor=MachineOperationsExecutor(repository=repository),
        last_maintenance_reader=reader,
        maintenance_cooldown_minutes=cooldown_minutes,
        bypass_reader=bypass_reader,
        service_calendar_timezone=service_calendar_timezone,
        inventory_gate=inventory_gate,  # type: ignore[arg-type]
    )


class _VisitGate:
    def __init__(self, *, suppress: bool = True, inventory_block: str | None = None) -> None:
        self.suppress = suppress
        self.inventory_block = inventory_block
        self.closed = 0

    def complete_maintenance_block_reason(
        self, machine_id: object, checked_at: object
    ) -> str | None:
        del machine_id, checked_at
        return self.inventory_block

    def suppress_coffee_revision(self, machine_id: object) -> bool:
        del machine_id
        return self.suppress

    def loading_photos_block_reason(self, machine_id: object, checked_at: object) -> str | None:
        del machine_id, checked_at
        return None

    def close_loading_order_after_visit_final(self, machine_id: object) -> None:
        del machine_id
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


def test_complete_maintenance_service_persists_event() -> None:
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    service = _complete_service(repository)
    _seed_revision(repository)
    completed_at = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)

    result = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=completed_at,
        ),
    )

    assert isinstance(result, MaintenanceCompleted)
    reloaded = repository.get(_MACHINE_ID)
    assert reloaded.last_maintenance_completed_at() == completed_at


def test_complete_maintenance_service_returns_already_completed_today() -> None:
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    service = _complete_service(repository)
    _seed_revision(repository)
    completed_at = datetime(2026, 5, 22, 10, 0, tzinfo=UTC)
    service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=completed_at,
        ),
    )

    second = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=datetime(2026, 5, 22, 18, 0, tzinfo=UTC),
        ),
    )

    assert isinstance(second, MaintenanceAlreadyCompletedToday)


def test_complete_maintenance_service_rejected_without_active_phase() -> None:
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    service = _complete_service(repository)

    result = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
        ),
    )

    assert isinstance(result, MaintenanceNotAllowed)


def test_complete_maintenance_returns_cooldown_active() -> None:
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    projection = InMemoryTechnicianLastMaintenanceProjection()
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH_A,
            machine_id=MachineId("vm-other"),
            completed_at=datetime(2026, 5, 22, 10, 0, tzinfo=UTC),
        ),
    )
    service = _complete_service(
        repository,
        projection=projection,
        cooldown_minutes=20,
    )
    _seed_revision(repository)

    result = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=datetime(2026, 5, 22, 10, 5, tzinfo=UTC),
        ),
    )

    assert isinstance(result, MaintenanceCooldownActive)


def test_complete_maintenance_succeeds_when_bypass_active() -> None:
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    projection = InMemoryTechnicianLastMaintenanceProjection()
    completed_at = datetime(2026, 5, 22, 10, 5, tzinfo=UTC)
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH_A,
            machine_id=MachineId("vm-other"),
            completed_at=datetime(2026, 5, 22, 10, 0, tzinfo=UTC),
        ),
    )
    bypass_reader = _FakeBypassReader(
        MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 5, 22),
            activated_at=completed_at,
        ),
    )
    service = _complete_service(
        repository,
        projection=projection,
        cooldown_minutes=20,
        bypass_reader=bypass_reader,
    )
    _seed_revision(repository)

    result = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=completed_at,
        ),
    )

    assert isinstance(result, MaintenanceCompleted)


def test_complete_maintenance_succeeds_awaiting_handover_when_bypass_active() -> None:
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    _seed_revision(repository)
    completed_at = datetime(2026, 5, 22, 18, 0, tzinfo=UTC)
    # Coffee phase: bypass skips hold, but acting technician still needs loading.
    aggregate = repository.get(_MACHINE_ID)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH_OTHER,
            submitted_at=completed_at - timedelta(minutes=1),
            form_id="form-loading",
            form_token="load-before-fm-maint",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)
    bypass_reader = _FakeBypassReader(
        MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 5, 22),
            activated_at=completed_at,
        ),
    )
    service = _complete_service(
        repository,
        cooldown_minutes=20,
        bypass_reader=bypass_reader,
    )
    result = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_OTHER,
            machine_id=_MACHINE_ID,
            completed_at=completed_at,
        ),
    )
    assert isinstance(result, MaintenanceCompleted)


def test_complete_maintenance_suppress_closes_order_via_gate() -> None:
    # happy: suppress + MaintenanceCompleted → close_loading_order_after_visit_final
    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    gate = _VisitGate(suppress=True, inventory_block=None)
    service = _complete_service(repository, inventory_gate=gate)
    completed_at = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    result = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=completed_at,
        ),
    )
    assert isinstance(result, MaintenanceCompleted)
    assert gate.closed == 1
    assert repository.get(_MACHINE_ID).last_maintenance_completed_at() == completed_at


def test_complete_maintenance_suppress_without_gate_close_when_blocked() -> None:
    # edge: inventory block → no MaintenanceCompleted, close не вызывался
    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    gate = _VisitGate(suppress=True, inventory_block="нужна инвентаризация")
    service = _complete_service(repository, inventory_gate=gate)
    result = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        ),
    )
    assert isinstance(result, MaintenanceNotAllowed)
    assert gate.closed == 0


def test_complete_maintenance_without_suppress_still_requires_revision() -> None:
    # error: без suppress / без ревизии → MaintenanceNotAllowed (прежний путь)
    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    service = _complete_service(repository)  # inventory_gate=None
    result = service.execute(
        CompleteMaintenanceCommand(
            technician_id=_TECH_A,
            machine_id=_MACHINE_ID,
            completed_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        ),
    )
    assert isinstance(result, MaintenanceNotAllowed)
