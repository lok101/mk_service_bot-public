from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.application.machine_operations.services import GetTechnicianRevisionOutlookService
from src.application.machine_operations.use_cases import GetTechnicianRevisionOutlookQuery
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations import CompleteRevision, LoadingSubmitted, SubmitLoading
from src.domain.models import RevisionSource, VendingMachine
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore

_TECH_A = TechnicianId("tech-a")
_MACHINE_ID = MachineId("vm-01")
_MSK = ZoneInfo("Europe/Moscow")
_COMPLETED_AT = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
_LOADING_AT = datetime(2026, 5, 15, 9, 0, tzinfo=UTC)


class _FakeVendingMachineRepository:
    def __init__(self, machines: list[VendingMachine]) -> None:
        self._machines = machines

    def list_available_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[VendingMachine]:
        return list(self._machines)

    def list_all(self) -> list[VendingMachine]:
        return list(self._machines)

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return _TECH_A

    def get(self, machine_id: MachineId) -> VendingMachine | None:
        for machine in self._machines:
            if machine.id == machine_id:
                return machine
        return None

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        return None

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return None


def _complete_revision(repository: EventSourcedMachineOperationsRepository) -> None:
    aggregate = repository.get(_MACHINE_ID)
    loading = aggregate.submit_loading(
        SubmitLoading(
            technician_id=_TECH_A,
            submitted_at=_LOADING_AT,
            form_id="form-loading",
            form_token="token-load-1",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    repository.save(aggregate)
    aggregate = repository.get(_MACHINE_ID)
    result = aggregate.complete_revision(
        CompleteRevision(
            technician_id=_TECH_A,
            completed_at=_COMPLETED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-revision",
            form_token="token-rev-1",
        ),
    )
    assert result is not None
    repository.save(aggregate)


def test_outlook_returns_responsible_machines_with_status() -> None:
    event_store = InMemoryEventStore()
    repo = EventSourcedMachineOperationsRepository(
        event_store=event_store,
        revision_interval_min_days=10,
        revision_interval_max_days=12,
        service_calendar_timezone=_MSK,
    )
    _complete_revision(repo)
    fake_vm_repo = _FakeVendingMachineRepository(
        [VendingMachine(id=_MACHINE_ID, name="VM 1")],
    )
    service = GetTechnicianRevisionOutlookService(
        machine_operations=repo,
        vending_machines=fake_vm_repo,
    )
    entries = service.execute(
        GetTechnicianRevisionOutlookQuery(
            technician_id=_TECH_A,
            checked_at=datetime(2026, 5, 16, tzinfo=UTC),
        ),
    )
    assert len(entries) == 1
    assert entries[0].machine_id == MachineId("vm-01")
    assert entries[0].responsibility_expires_at is not None
    assert entries[0].revision_due_status == "not_due"


def test_repository_passes_revision_interval_settings() -> None:
    event_store = InMemoryEventStore()
    repo = EventSourcedMachineOperationsRepository(
        event_store=event_store,
        revision_interval_min_days=10,
        revision_interval_max_days=12,
        service_calendar_timezone=_MSK,
    )
    _complete_revision(repo)
    reloaded = repo.get(_MACHINE_ID)
    assert reloaded.responsibility_expires_at() is not None
