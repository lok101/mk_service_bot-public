from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr
from tests.infrastructure.composition_helpers import _StubVendingMachineRepository

from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import (
    CompleteMaintenanceService,
    CreateLoadingFormService,
    GetServiceCapabilitiesService,
    GetTechnicianRevisionOutlookService,
    ListAvailableMachinesService,
)
from src.application.master_data import (
    InMemoryMasterDataStores,
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.application.photo_batches.errors import PhotoBatchRejectedError
from src.config.google_forms import GoogleFormsSettings
from src.config.mongodb import MongoSettings
from src.config.service_rules import ServiceRulesSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import PhotoRef
from src.domain.results import loading_photos_excess_count_reason
from src.infrastructure.composition.bundles.machine_ops import MachineOpsBundle
from src.infrastructure.composition.wiring.wire_photos import wire_photos
from src.infrastructure.events import SyncDomainEventPublisher
from src.infrastructure.integrations.google.forms import (
    GoogleFormsLoadingFormLinkProvider,
    GoogleFormsRevisionFormLinkProvider,
)
from src.infrastructure.machine_operations.maintenance_cooldown_bypass_memory import (
    NullMaintenanceCooldownBypassReader,
)
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore

_MM_ID = MachineId("mm-photos-1")
_COFFEE_ID = MachineId("coffee-photos-1")
_TECH = TechnicianId("tech-wire-photos")
_SUBMITTED_AT = datetime(2026, 5, 20, 11, 0, tzinfo=UTC)


def _settings(*, max_count: int = 10) -> Settings:
    return Settings.model_construct(
        mongodb=MongoSettings.model_construct(uri=None),
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("dev-bot-token-16chars"),
            webhook_public_host="",
        ),
        google_forms=GoogleFormsSettings.model_construct(
            webhook_secret=SecretStr("dev-webhook-secret"),
            revision_form_token_secret=SecretStr("dev-revision-form-token-secret"),
            loading_form_token_secret=SecretStr("dev-loading-form-token-secret"),
            revision_form_url="https://forms.example/revision",
            loading_form_url="https://forms.example/loading",
            revision_form_token_entry_id="entry.1",
            loading_form_token_entry_id="entry.2",
            technician_warehouse_inventory_form_url="https://forms.example/warehouse",
            technician_warehouse_inventory_form_token_secret=SecretStr(
                "dev-warehouse-inventory-form-token-secret",
            ),
            technician_warehouse_inventory_form_token_entry_id="entry.3",
            token_field_name="token",
        ),
        service_rules=ServiceRulesSettings.model_construct(
            loading_photos_min_count=2,
            loading_photos_max_count=max_count,
            maintenance_cooldown_minutes=0,
        ),
    )


def _machine_ops() -> MachineOpsBundle:
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    projection = InMemoryTechnicianLastMaintenanceProjection()
    publisher = SyncDomainEventPublisher()
    executor = MachineOperationsExecutor(
        repository=repository,
        publisher=publisher,
        technician_last_maintenance=projection,
    )
    vending = _StubVendingMachineRepository()
    bypass = NullMaintenanceCooldownBypassReader()
    tz = ZoneInfo("Europe/Moscow")
    revision_links = GoogleFormsRevisionFormLinkProvider(
        form_url="https://example.com/revision",
        token_entry_id="entry.1",
        token_secret="secret",
    )
    loading_links = GoogleFormsLoadingFormLinkProvider(
        form_url="https://example.com/loading",
        token_entry_id="entry.2",
        token_secret="secret",
    )
    return MachineOpsBundle(
        event_store=event_store,
        repository=repository,
        executor=executor,
        technician_last_maintenance=projection,
        vending_machines=vending,
        revision_form_links=revision_links,
        loading_form_links=loading_links,
        list_available_machines=ListAvailableMachinesService(repository=vending),
        get_service_capabilities=GetServiceCapabilitiesService(
            machine_operations=repository,
            revision_form_links=revision_links,
            last_maintenance_reader=projection,
            maintenance_cooldown_minutes=0,
            bypass_reader=bypass,
            service_calendar_timezone=tz,
        ),
        get_technician_revision_outlook=GetTechnicianRevisionOutlookService(
            machine_operations=repository,
            vending_machines=vending,
        ),
        complete_maintenance=CompleteMaintenanceService(
            executor=executor,
            last_maintenance_reader=projection,
            maintenance_cooldown_minutes=0,
            bypass_reader=bypass,
            service_calendar_timezone=tz,
        ),
        create_loading_form=CreateLoadingFormService(form_links=loading_links),
        maintenance_cooldown_bypass=bypass,
        service_calendar_timezone=tz,
        maintenance_cooldown_minutes=0,
    )


def _photos(count: int) -> tuple[PhotoRef, ...]:
    return tuple(
        PhotoRef(
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )
        for index in range(1, count + 1)
    )


def _machine(machine_id: MachineId, kind: MachineKind) -> MasterMachine:
    return MasterMachine(
        machine_id=machine_id,
        kind=kind,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
    )


def test_wire_photos_shared_machines_mm_excess_coffee_env_max() -> None:
    machines = InMemoryMasterDataStores().machines
    machines.upsert(_machine(_MM_ID, MachineKind.MICRO_MARKET))
    machines.upsert(_machine(_COFFEE_ID, MachineKind.COFFEE))
    bundle = wire_photos(
        _settings(max_count=10),
        mongo_client=None,
        machine_ops=_machine_ops(),
        machines=machines,
    )
    accept = bundle.accept_loading_photos

    with pytest.raises(
        PhotoBatchRejectedError,
        match=loading_photos_excess_count_reason(2),
    ):
        accept.execute(
            batch_id=BatchId("batch-mm-excess"),
            technician_id=_TECH,
            machine_id=_MM_ID,
            submitted_at=_SUBMITTED_AT,
            photos=_photos(3),
        )

    with pytest.raises(
        PhotoBatchRejectedError,
        match=loading_photos_excess_count_reason(10),
    ):
        accept.execute(
            batch_id=BatchId("batch-coffee-excess"),
            technician_id=_TECH,
            machine_id=_COFFEE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=_photos(11),
        )
