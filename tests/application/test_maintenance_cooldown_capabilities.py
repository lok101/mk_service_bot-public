from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import GetServiceCapabilitiesService
from src.application.machine_operations.use_cases import GetServiceCapabilitiesCommand
from src.domain.calendar import calendar_anchor
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations import CompleteRevision, LoadingSubmitted, SubmitLoading
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot
from src.domain.models import PrefilledFormLink, RevisionSource
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore

_TECH = TechnicianId("tech-a")
_TECH_OTHER = TechnicianId("tech-other")
_MACHINE_A = MachineId("vm-a")
_MACHINE_B = MachineId("vm-b")
_T_REV = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
_T_MAINT_A = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
_T_CHECK = datetime(2026, 7, 2, 10, 5, tzinfo=UTC)
_T_FM = datetime(2026, 7, 2, 18, 0, tzinfo=UTC)
_MSK = ZoneInfo("Europe/Moscow")


class _StubRevisionFormLinkProvider:
    @staticmethod
    def create_link(
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink:
        return PrefilledFormLink(url="https://example.com/revision")


def _seed_revision(
    repository: EventSourcedMachineOperationsRepository,
    machine_id: MachineId,
    *,
    completed_at: datetime = _T_REV,
) -> None:
    executor = MachineOperationsExecutor(repository=repository)
    form_token = f"token-{machine_id.value}"
    loading = executor.execute(
        machine_id,
        lambda aggregate: aggregate.submit_loading(
            SubmitLoading(
                technician_id=_TECH,
                submitted_at=completed_at - timedelta(minutes=1),
                form_id="form-loading",
                form_token=f"load-before-{form_token}",
            ),
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    executor.execute(
        machine_id,
        lambda aggregate: aggregate.complete_revision(
            CompleteRevision(
                technician_id=_TECH,
                completed_at=completed_at,
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-rev",
                form_token=form_token,
            ),
        ),
    )


def _capabilities_service(
    repository: EventSourcedMachineOperationsRepository,
    projection: InMemoryTechnicianLastMaintenanceProjection,
    *,
    cooldown_minutes: int = 20,
    bypass_reader: object | None = None,
    service_calendar_timezone: ZoneInfo = _MSK,
) -> GetServiceCapabilitiesService:
    return GetServiceCapabilitiesService(
        machine_operations=repository,
        revision_form_links=_StubRevisionFormLinkProvider(),
        last_maintenance_reader=projection,
        maintenance_cooldown_minutes=cooldown_minutes,
        bypass_reader=bypass_reader,
        service_calendar_timezone=service_calendar_timezone,
    )


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


@patch("src.application.machine_operations.services.datetime")
def test_capabilities_block_complete_and_photos_when_cooldown_active(
    mock_datetime: object,
) -> None:
    mock_datetime.now.return_value = _T_CHECK  # type: ignore[attr-defined]
    mock_datetime.UTC = UTC  # type: ignore[attr-defined]

    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    _seed_revision(repository, _MACHINE_B)
    projection = InMemoryTechnicianLastMaintenanceProjection()
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_MACHINE_A,
            completed_at=_T_MAINT_A,
        ),
    )
    service = _capabilities_service(repository, projection)

    caps = service.execute(
        GetServiceCapabilitiesCommand(technician_id=_TECH, machine_id=_MACHINE_B),
    )

    assert caps.can_complete_maintenance is False
    assert caps.can_submit_loading_photos is False
    assert caps.can_submit_loading is True
    assert caps.can_complete_revision is False


@patch("src.application.machine_operations.services.datetime")
def test_capabilities_allow_complete_when_bypass_active(
    mock_datetime: object,
) -> None:
    mock_datetime.now.return_value = _T_CHECK  # type: ignore[attr-defined]
    mock_datetime.UTC = UTC  # type: ignore[attr-defined]

    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    _seed_revision(repository, _MACHINE_B)
    projection = InMemoryTechnicianLastMaintenanceProjection()
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_MACHINE_A,
            completed_at=_T_MAINT_A,
        ),
    )
    bypass_reader = _FakeBypassReader(
        MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 7, 2),
            activated_at=_T_CHECK,
        ),
    )
    service = _capabilities_service(
        repository,
        projection,
        bypass_reader=bypass_reader,
    )

    caps = service.execute(
        GetServiceCapabilitiesCommand(technician_id=_TECH, machine_id=_MACHINE_B),
    )

    assert caps.can_complete_maintenance is True
    assert caps.can_submit_loading_photos is True


@patch("src.application.machine_operations.services.datetime")
def test_capabilities_allow_photos_when_maintenance_completed_today_on_current_machine(
    mock_datetime: object,
) -> None:
    mock_datetime.now.return_value = _T_CHECK  # type: ignore[attr-defined]
    mock_datetime.UTC = UTC  # type: ignore[attr-defined]

    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    _seed_revision(repository, _MACHINE_B)
    executor = MachineOperationsExecutor(repository=repository)
    from src.domain.machine_operations import CompleteMaintenance

    executor.execute(
        _MACHINE_B,
        lambda aggregate: aggregate.complete_maintenance(
            CompleteMaintenance(technician_id=_TECH, completed_at=_T_REV),
            checked_at=_T_REV,
        ),
    )
    projection = InMemoryTechnicianLastMaintenanceProjection()
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_MACHINE_A,
            completed_at=_T_MAINT_A,
        ),
    )
    service = _capabilities_service(repository, projection)

    caps = service.execute(
        GetServiceCapabilitiesCommand(technician_id=_TECH, machine_id=_MACHINE_B),
    )

    assert caps.maintenance_completed_today is True
    assert caps.can_submit_loading_photos is True
    assert caps.can_complete_maintenance is False


@patch("src.application.machine_operations.services.datetime")
def test_capabilities_loading_and_revision_unaffected_by_cooldown(
    mock_datetime: object,
) -> None:
    mock_datetime.now.return_value = _T_CHECK  # type: ignore[attr-defined]
    mock_datetime.UTC = UTC  # type: ignore[attr-defined]

    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    _seed_revision(repository, _MACHINE_B)
    projection = InMemoryTechnicianLastMaintenanceProjection()
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_MACHINE_A,
            completed_at=_T_MAINT_A,
        ),
    )
    service = _capabilities_service(repository, projection)

    caps = service.execute(
        GetServiceCapabilitiesCommand(technician_id=_TECH, machine_id=_MACHINE_B),
    )

    assert caps.can_submit_loading is True
    assert caps.can_complete_revision is False


@patch("src.application.machine_operations.services.datetime")
def test_capabilities_ignore_cooldown_when_disabled(mock_datetime: object) -> None:
    mock_datetime.now.return_value = _T_CHECK  # type: ignore[attr-defined]
    mock_datetime.UTC = UTC  # type: ignore[attr-defined]

    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    _seed_revision(repository, _MACHINE_B)
    projection = InMemoryTechnicianLastMaintenanceProjection()
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_MACHINE_A,
            completed_at=_T_MAINT_A,
        ),
    )
    service = _capabilities_service(repository, projection, cooldown_minutes=0)

    caps = service.execute(
        GetServiceCapabilitiesCommand(technician_id=_TECH, machine_id=_MACHINE_B),
    )

    assert caps.can_complete_maintenance is True
    assert caps.can_submit_loading_photos is True


@patch("src.application.machine_operations.services.datetime")
def test_capabilities_force_majeure_awaiting_handover_effective_caps(
    mock_datetime: object,
) -> None:
    mock_datetime.now.return_value = _T_FM  # type: ignore[attr-defined]
    mock_datetime.UTC = UTC  # type: ignore[attr-defined]

    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    _seed_revision(repository, _MACHINE_B)
    bypass_reader = _FakeBypassReader(
        MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 7, 2),
            activated_at=_T_FM,
        ),
    )
    service = _capabilities_service(
        repository,
        InMemoryTechnicianLastMaintenanceProjection(),
        bypass_reader=bypass_reader,
    )
    caps = service.execute(
        GetServiceCapabilitiesCommand(technician_id=_TECH_OTHER, machine_id=_MACHINE_B),
    )
    assert caps.responsibility_phase == "responsible"
    # Coffee phase: force majeure skips hold; revision/photos need own loading.
    assert caps.can_complete_revision is False
    assert caps.revision_form_link is None
    assert caps.revision_due_status is None
    assert caps.responsibility_expires_at == calendar_anchor(_T_FM, _MSK)
    assert caps.can_submit_loading is True
    # ISS-018: complete без loading; фото остаются gated
    assert caps.can_complete_maintenance is True
    assert caps.can_submit_loading_photos is False


@patch("src.application.machine_operations.services.datetime")
def test_capabilities_force_majeure_responsible_does_not_rewrite_due_line(
    mock_datetime: object,
) -> None:
    mock_datetime.now.return_value = _T_CHECK  # type: ignore[attr-defined]
    mock_datetime.UTC = UTC  # type: ignore[attr-defined]

    repository = EventSourcedMachineOperationsRepository(event_store=InMemoryEventStore())
    _seed_revision(repository, _MACHINE_B)
    bypass_reader = _FakeBypassReader(
        MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 7, 2),
            activated_at=_T_CHECK,
        ),
    )
    service = _capabilities_service(
        repository,
        InMemoryTechnicianLastMaintenanceProjection(),
        bypass_reader=bypass_reader,
        cooldown_minutes=0,
    )
    caps = service.execute(
        GetServiceCapabilitiesCommand(technician_id=_TECH, machine_id=_MACHINE_B),
    )
    assert caps.responsibility_phase == "responsible"
    assert caps.revision_due_status is None
    assert caps.can_complete_revision is False
