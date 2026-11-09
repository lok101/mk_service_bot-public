from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import (
    GetServiceCapabilitiesService,
    RegisterLoadingFromFormService,
    RegisterRevisionFromFormService,
)
from src.application.machine_operations.use_cases import (
    GetServiceCapabilitiesCommand,
    RegisterLoadingFromFormCommand,
    RegisterRevisionFromFormCommand,
)
from src.application.micromarket_loading.complete_maintenance_gate import (
    MICROMARKET_INVENTORY_REQUIRED_REASON,
    MICROMARKET_LOADING_PHOTOS_OPEN_REASON,
)
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted, RevisionCompleted
from src.domain.models import PrefilledFormLink, RevisionSource
from src.domain.results import maintenance_cooldown_reason
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot
from src.infrastructure.events import SyncDomainEventPublisher
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import (
    EventSourcedMachineOperationsRepository,
    InMemoryEventStore,
)
from src.infrastructure.testing import (
    OTHER_TECHNICIAN_ID,
    TEST_TECHNICIAN_ID,
    seed_test_machine_revision_events,
)


class _StubRevisionFormLinkProvider:
    @staticmethod
    def create_link(
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink:
        return PrefilledFormLink(
            url=f"https://example.com/revision?tech={technician_id.value}&vm={machine_id.value}",
        )


class _CountingRevisionFormLinkProvider(_StubRevisionFormLinkProvider):
    def __init__(self) -> None:
        self.create_link_calls = 0

    def create_link(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink:
        self.create_link_calls += 1
        return _StubRevisionFormLinkProvider.create_link(technician_id, machine_id)


def _build_services() -> tuple[
    GetServiceCapabilitiesService,
    RegisterRevisionFromFormService,
    RegisterLoadingFromFormService,
    InMemoryEventStore,
    SyncDomainEventPublisher,
]:
    event_store = InMemoryEventStore()
    seed_test_machine_revision_events(event_store)
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    publisher = SyncDomainEventPublisher()
    executor = MachineOperationsExecutor(
        repository=repository,
        publisher=publisher,
    )
    return (
        GetServiceCapabilitiesService(
            machine_operations=repository,
            revision_form_links=_StubRevisionFormLinkProvider(),
            last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
            maintenance_cooldown_minutes=0,
        ),
        RegisterRevisionFromFormService(executor=executor),
        RegisterLoadingFromFormService(executor=executor),
        event_store,
        publisher,
    )


def test_get_service_capabilities_active_for_seeded_machine() -> None:
    get_capabilities, _, _, _, _ = _build_services()

    result = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=MachineId("vm-01"),
        ),
    )

    assert result.responsibility_phase == "responsible"
    assert result.can_submit_loading is True
    assert result.revision_form_link is None


def test_get_service_capabilities_revision_link_only_awaiting_handover() -> None:
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(days=1)
    responsible_machine_id = MachineId("vm-responsible-near-deadline")
    event_store = InMemoryEventStore()
    event_store.append(
        RevisionCompleted(
            event_id=EventId("event-responsible-near"),
            revision_id=RevisionId("rev-responsible-near"),
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=responsible_machine_id,
            completed_at=now - timedelta(days=5),
            occurred_at=now - timedelta(days=5),
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-responsible-near",
            form_token="token-responsible-near",
            responsibility_expires_at=expires_at,
        ),
        expected_version=0,
    )
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    revision_links = _CountingRevisionFormLinkProvider()
    get_capabilities = GetServiceCapabilitiesService(
        machine_operations=repository,
        revision_form_links=revision_links,
        last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
        maintenance_cooldown_minutes=0,
    )

    responsible = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=responsible_machine_id,
        ),
    )
    assert responsible.responsibility_phase == "responsible"
    assert responsible.revision_due_status == "not_due"
    assert revision_links.create_link_calls == 0
    assert responsible.revision_form_link is None

    handover = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=responsible_machine_id,
        ),
    )
    assert handover.responsibility_phase == "awaiting_handover"
    assert handover.can_submit_loading is True
    assert handover.can_complete_revision is False
    assert revision_links.create_link_calls == 1

    event_store.append(
        LoadingSubmitted(
            event_id=EventId("event-loading-handover"),
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=responsible_machine_id,
            submitted_at=now,
            occurred_at=now,
            form_id="form-loading-handover",
            form_token="token-loading-handover",
        ),
        expected_version=1,
    )
    after_loading = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=responsible_machine_id,
        ),
    )
    assert after_loading.responsibility_phase == "awaiting_handover"
    assert after_loading.can_complete_revision is True
    assert revision_links.create_link_calls == 2
    assert after_loading.revision_form_link is not None
    assert responsible_machine_id.value in after_loading.revision_form_link.url


def test_get_service_capabilities_active_skips_form_link_creation() -> None:
    now = datetime.now(tz=UTC)
    machine_id = MachineId("vm-active")
    event_store = InMemoryEventStore()
    event_store.append(
        RevisionCompleted(
            event_id=EventId("event-active"),
            revision_id=RevisionId("rev-active"),
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            completed_at=now - timedelta(days=1),
            occurred_at=now - timedelta(days=1),
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-active",
            form_token="token-active",
            responsibility_expires_at=now + timedelta(days=30),
        ),
        expected_version=0,
    )
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    revision_links = _CountingRevisionFormLinkProvider()
    get_capabilities = GetServiceCapabilitiesService(
        machine_operations=repository,
        revision_form_links=revision_links,
        last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
        maintenance_cooldown_minutes=0,
    )

    get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
        ),
    )

    assert revision_links.create_link_calls == 0


def test_get_service_capabilities_onboarding_for_other_technician_on_seeded_machine() -> None:
    get_capabilities, _, register_loading, _, _ = _build_services()
    machine_id = MachineId("vm-01")

    before_loading = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=machine_id,
        ),
    )
    assert before_loading.responsibility_phase == "awaiting_handover"
    assert before_loading.can_complete_revision is False
    assert before_loading.can_submit_loading is True
    assert before_loading.revision_form_link is None

    register_loading.execute(
        RegisterLoadingFromFormCommand(
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=datetime.now(tz=UTC),
            form_id="form-onboard-loading",
            form_token="token-onboard-loading",
        ),
    )
    after_loading = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=machine_id,
        ),
    )
    assert after_loading.can_complete_revision is True
    assert after_loading.revision_form_link is not None
    assert "vm-01" in after_loading.revision_form_link.url


def test_register_revision_persists_and_opens_active_phase() -> None:
    get_capabilities, register_revision, register_loading, event_store, _ = _build_services()
    machine_id = MachineId("vm-99")
    loading_at = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    submitted_at = datetime(2026, 5, 19, 10, 0, tzinfo=UTC)

    loading = register_loading.execute(
        RegisterLoadingFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=loading_at,
            form_id="form-loading",
            form_token="token-pre-rev-loading",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)

    event = register_revision.execute(
        RegisterRevisionFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=submitted_at,
            form_id="form-revision",
            form_token="token-new-revision",
        ),
    )

    assert isinstance(event, RevisionCompleted)
    assert event.machine_id == machine_id
    assert len(event_store.get_events_for_machine(machine_id)) == 2

    caps = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
        ),
    )
    assert caps.responsibility_phase == "responsible"


def test_register_revision_is_idempotent() -> None:
    _, register_revision, register_loading, event_store, _ = _build_services()
    machine_id = MachineId("vm-98")

    loading = register_loading.execute(
        RegisterLoadingFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
            form_id="form-loading",
            form_token="token-pre-idempotent-loading",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)

    command = RegisterRevisionFromFormCommand(
        technician_id=TEST_TECHNICIAN_ID,
        machine_id=machine_id,
        submitted_at=datetime(2026, 5, 19, 10, 0, tzinfo=UTC),
        form_id="form-revision",
        form_token="token-idempotent",
    )

    first = register_revision.execute(command)
    second = register_revision.execute(command)

    assert isinstance(first, RevisionCompleted)
    assert second is first
    assert len(event_store.get_events_for_machine(machine_id)) == 2


def test_register_loading_accepted_in_handover_without_revision() -> None:
    _, _, register_loading, event_store, _ = _build_services()
    machine_id = MachineId("vm-97")
    submitted_at = datetime(2026, 5, 19, 11, 0, tzinfo=UTC)

    result = register_loading.execute(
        RegisterLoadingFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=submitted_at,
            form_id="form-loading",
            form_token="token-loading",
        ),
    )

    assert isinstance(result, LoadingSubmitted)
    assert len(event_store.get_events_for_machine(machine_id)) == 1


def test_register_loading_persists_event_in_active_phase() -> None:
    _, register_revision, register_loading, event_store, _ = _build_services()
    machine_id = MachineId("vm-96")
    loading_at = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    submitted_at = datetime(2026, 5, 19, 11, 0, tzinfo=UTC)

    pre_loading = register_loading.execute(
        RegisterLoadingFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=loading_at,
            form_id="form-loading",
            form_token="token-pre-rev-loading",
        ),
    )
    assert isinstance(pre_loading, LoadingSubmitted)

    register_revision.execute(
        RegisterRevisionFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=datetime(2026, 5, 19, 10, 0, tzinfo=UTC),
            form_id="form-revision",
            form_token="token-rev",
        ),
    )

    result = register_loading.execute(
        RegisterLoadingFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=submitted_at,
            form_id="form-loading",
            form_token="token-loading",
        ),
    )

    assert isinstance(result, LoadingSubmitted)
    assert result.form_token == "token-loading"
    assert len(event_store.get_events_for_machine(machine_id)) == 3


def test_get_service_capabilities_returns_onboarding_after_revision_interval() -> None:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(
        event_store=event_store,
        revision_interval_min_days=7,
        revision_interval_max_days=7,
    )
    publisher = SyncDomainEventPublisher()
    executor = MachineOperationsExecutor(repository=repository, publisher=publisher)
    register_revision = RegisterRevisionFromFormService(executor=executor)
    register_loading = RegisterLoadingFromFormService(executor=executor)
    machine_id = MachineId("vm-interval")
    loading_at = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    submitted_at = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    stale_check = submitted_at + timedelta(days=7)

    loading = register_loading.execute(
        RegisterLoadingFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=loading_at,
            form_id="form-loading",
            form_token="token-interval-loading",
        ),
    )
    assert isinstance(loading, LoadingSubmitted)

    register_revision.execute(
        RegisterRevisionFromFormCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=submitted_at,
            form_id="form-revision",
            form_token="token-interval",
        ),
    )

    aggregate = repository.get(machine_id)
    capabilities = aggregate.get_service_capabilities(
        TEST_TECHNICIAN_ID,
        checked_at=stale_check,
        revision_form_link=PrefilledFormLink(url="https://example.com/revision"),
    )
    assert capabilities.responsibility_phase == "awaiting_handover"
    # overdue handover without a new loading → revision gated
    assert capabilities.can_complete_revision is False
    assert capabilities.loading_completed is False


class _VisitGate:
    def __init__(
        self,
        *,
        suppress: bool = True,
        inventory_block: str | None = None,
        photos_block: str | None = None,
    ) -> None:
        self.suppress = suppress
        self.inventory_block = inventory_block
        self.photos_block = photos_block
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

    def loading_photos_block_reason(
        self,
        machine_id: object,
        checked_at: object,
    ) -> str | None:
        del machine_id, checked_at
        return self.photos_block

    def close_loading_order_after_visit_final(self, machine_id: object) -> None:
        del machine_id
        self.closed += 1


def test_get_service_capabilities_suppresses_coffee_link_while_awaiting_handover() -> None:
    # happy: suppress + awaiting_handover → нет ValueError, нет кофейной ссылки/загрузки
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    revision_links = _CountingRevisionFormLinkProvider()
    gate = _VisitGate(suppress=True)
    service = GetServiceCapabilitiesService(
        machine_operations=repository,
        revision_form_links=revision_links,
        last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
        maintenance_cooldown_minutes=0,
        inventory_gate=gate,  # type: ignore[arg-type]
    )
    machine_id = MachineId("mm-701")
    result = service.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
        ),
    )
    assert result.responsibility_phase == "awaiting_handover"
    assert result.can_complete_revision is False
    assert result.revision_form_link is None
    assert result.can_submit_loading is False
    assert revision_links.create_link_calls == 0
    assert result.can_complete_maintenance is True
    assert result.can_submit_loading_photos is True


def test_get_service_capabilities_suppress_hides_loading_when_responsible() -> None:
    # edge: suppress + responsible → агрегат оставил бы can_submit_loading True
    now = datetime.now(tz=UTC)
    machine_id = MachineId("mm-responsible")
    event_store = InMemoryEventStore()
    event_store.append(
        RevisionCompleted(
            event_id=EventId("event-mm-resp"),
            revision_id=RevisionId("rev-mm-resp"),
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            completed_at=now - timedelta(days=5),
            occurred_at=now - timedelta(days=5),
            source=RevisionSource.GOOGLE_FORM,
            form_id="form-mm-resp",
            form_token="token-mm-resp",
            responsibility_expires_at=now + timedelta(days=1),
        ),
        expected_version=0,
    )
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    revision_links = _CountingRevisionFormLinkProvider()
    gate = _VisitGate(suppress=True)
    service = GetServiceCapabilitiesService(
        machine_operations=repository,
        revision_form_links=revision_links,
        last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
        maintenance_cooldown_minutes=0,
        inventory_gate=gate,  # type: ignore[arg-type]
    )
    result = service.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
        ),
    )
    assert result.responsibility_phase == "responsible"
    assert result.can_complete_revision is False
    assert result.revision_form_link is None
    assert result.can_submit_loading is False
    assert revision_links.create_link_calls == 0


def test_get_service_capabilities_without_suppress_still_creates_coffee_link() -> None:
    # error/regression: кофе без suppress по-прежнему получает ссылку после загрузки
    get_capabilities, _, register_loading, _, _ = _build_services()
    machine_id = MachineId("vm-01")
    before_loading = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=machine_id,
        ),
    )
    assert before_loading.responsibility_phase == "awaiting_handover"
    assert before_loading.can_submit_loading is True
    assert before_loading.revision_form_link is None

    register_loading.execute(
        RegisterLoadingFromFormCommand(
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=machine_id,
            submitted_at=datetime.now(tz=UTC),
            form_id="form-coffee-loading",
            form_token="token-coffee-loading",
        ),
    )
    result = get_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=OTHER_TECHNICIAN_ID,
            machine_id=machine_id,
        ),
    )
    assert result.can_complete_revision is True
    assert result.revision_form_link is not None


def test_suppress_inventory_blocks_both_visit_buttons_with_reasons() -> None:
    # edge: нет инвентаризации → обе кнопки ложны, причина инвентаризации
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    gate = _VisitGate(
        suppress=True,
        inventory_block=MICROMARKET_INVENTORY_REQUIRED_REASON,
    )
    service = GetServiceCapabilitiesService(
        machine_operations=repository,
        revision_form_links=_StubRevisionFormLinkProvider(),
        last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
        maintenance_cooldown_minutes=0,
        inventory_gate=gate,  # type: ignore[arg-type]
    )
    result = service.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=MachineId("mm-inv"),
        ),
    )
    assert result.can_complete_maintenance is False
    assert result.can_submit_loading_photos is False
    assert result.complete_maintenance_block_reason == MICROMARKET_INVENTORY_REQUIRED_REASON
    assert result.loading_photos_block_reason == MICROMARKET_INVENTORY_REQUIRED_REASON


def test_suppress_open_order_blocks_both_visit_buttons() -> None:
    # edge: ордер open → обе кнопки визита недоступны (тот же reason)
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    gate = _VisitGate(
        suppress=True,
        inventory_block=MICROMARKET_LOADING_PHOTOS_OPEN_REASON,
        photos_block=MICROMARKET_LOADING_PHOTOS_OPEN_REASON,
    )
    service = GetServiceCapabilitiesService(
        machine_operations=repository,
        revision_form_links=_StubRevisionFormLinkProvider(),
        last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
        maintenance_cooldown_minutes=0,
        inventory_gate=gate,  # type: ignore[arg-type]
    )
    result = service.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=MachineId("mm-open"),
        ),
    )
    assert result.can_complete_maintenance is False
    assert result.can_submit_loading_photos is False
    assert result.complete_maintenance_block_reason == MICROMARKET_LOADING_PHOTOS_OPEN_REASON
    assert result.loading_photos_block_reason == MICROMARKET_LOADING_PHOTOS_OPEN_REASON


def test_suppress_pause_blocks_visit_while_awaiting_handover() -> None:
    # edge: пауза гасит визит и при awaiting_handover
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    projection = InMemoryTechnicianLastMaintenanceProjection()
    now = datetime.now(tz=UTC)
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=MachineId("other-vm"),
            completed_at=now - timedelta(minutes=5),
        ),
    )
    gate = _VisitGate(suppress=True)
    service = GetServiceCapabilitiesService(
        machine_operations=repository,
        revision_form_links=_StubRevisionFormLinkProvider(),
        last_maintenance_reader=projection,
        maintenance_cooldown_minutes=20,
        service_calendar_timezone=ZoneInfo("Europe/Moscow"),
        inventory_gate=gate,  # type: ignore[arg-type]
    )
    result = service.execute(
        GetServiceCapabilitiesCommand(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=MachineId("mm-pause"),
        ),
    )
    assert result.responsibility_phase == "awaiting_handover"
    assert result.can_complete_maintenance is False
    assert result.can_submit_loading_photos is False
    pause = maintenance_cooldown_reason(20)
    assert result.complete_maintenance_block_reason == pause
    assert result.loading_photos_block_reason == pause
