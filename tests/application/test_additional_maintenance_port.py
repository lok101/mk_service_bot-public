from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.additional_maintenance import (
    AlwaysDenyAdditionalMaintenance,
)
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
from src.domain.models import RevisionSource
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import (
    EventSourcedMachineOperationsRepository,
    InMemoryEventStore,
)

_MACHINE_ID = MachineId("vm-01")
_TECH_A = TechnicianId("tech-a")
_MSK = ZoneInfo("Europe/Moscow")
_COMPLETED_AT = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


@beartype
@dataclass(frozen=True, slots=True)
class _Allow:
    value: bool

    def allows(self, machine_id: MachineId, at: datetime) -> bool:
        return self.value


def test_always_deny_additional_maintenance_returns_false() -> None:
    port = AlwaysDenyAdditionalMaintenance()
    assert port.allows(MachineId("vm-01"), datetime(2026, 8, 12, tzinfo=UTC)) is False


def test_complete_maintenance_service_passes_allow_flag_when_port_true() -> None:
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    aggregate = repository.get(_MACHINE_ID)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH_A,
            submitted_at=_COMPLETED_AT - timedelta(minutes=1),
            form_id="form-loading",
            form_token="load-before-token-rev-1",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)
    aggregate = repository.get(_MACHINE_ID)
    revision = aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH_A,
            completed_at=_COMPLETED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert isinstance(revision, RevisionCompleted)
    repository.save(aggregate)

    service = CompleteMaintenanceService(
        executor=MachineOperationsExecutor(repository=repository),
        last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
        maintenance_cooldown_minutes=0,
        service_calendar_timezone=_MSK,
        additional_maintenance=_Allow(True),
    )
    command = CompleteMaintenanceCommand(
        technician_id=_TECH_A,
        machine_id=_MACHINE_ID,
        completed_at=_COMPLETED_AT,
    )
    first = service.execute(command)
    second = service.execute(command)
    assert isinstance(first, MaintenanceCompleted)
    assert isinstance(second, MaintenanceCompleted)
