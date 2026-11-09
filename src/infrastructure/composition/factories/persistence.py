from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.form_submissions.ports import (
    ExternalSideEffectRegistry,
    FormSubmissionStore,
)
from src.application.machine_operations.ports import (
    EventStore,
    MaintenanceCooldownBypassReader,
    MaintenanceCooldownBypassStore,
    OutboxStore,
    TechnicianLastMaintenanceProjection,
)
from src.application.matrix_automation.ports import MatrixPriceSnapshotStore
from src.application.outbox.ports import OutboxAdminStore
from src.application.technician_accountability.ports import (
    TechnicianAccountabilityEventStore,
    TechnicianAccountabilityRepository,
)
from src.config.settings import Settings
from src.infrastructure.form_submissions import InMemoryFormSubmissionStore
from src.infrastructure.machine_operations.maintenance_cooldown_bypass_memory import (
    NullMaintenanceCooldownBypassReader,
)
from src.infrastructure.machine_operations.maintenance_cooldown_bypass_mongo import (
    MongoMaintenanceCooldownBypassStore,
)
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.machine_operations.technician_last_maintenance_mongo import (
    MongoTechnicianLastMaintenanceProjection,
)
from src.infrastructure.matrix_automation.memory_snapshots import InMemoryMatrixPriceSnapshotStore
from src.infrastructure.matrix_automation.mongo_snapshots import MongoMatrixPriceSnapshotStore
from src.infrastructure.memory import InMemoryEventStore
from src.infrastructure.memory_side_effects import InMemoryExternalSideEffectRegistry
from src.infrastructure.mongodb import MongoEventStore
from src.infrastructure.mongodb.connection import create_mongo_client
from src.infrastructure.mongodb.external_side_effects import MongoExternalSideEffectRegistry
from src.infrastructure.mongodb.form_submissions import MongoFormSubmissionStore
from src.infrastructure.mongodb.technician_accountability import (
    MongoTechnicianAccountabilityEventStore,
    MongoTechnicianAccountabilityRepository,
)
from src.infrastructure.outbox import InMemoryOutboxStore, MongoOutboxStore
from src.infrastructure.technician_accountability.memory import (
    InMemoryTechnicianAccountabilityEventStore,
)


@beartype
def build_mongo_client(settings: Settings) -> MongoClient[dict[str, Any]] | None:
    mongo = settings.mongodb
    if not mongo.is_configured:
        return None
    return create_mongo_client(mongo)


@beartype
def build_event_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> EventStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoEventStore.from_settings(mongo, client=client)
    return InMemoryEventStore()


@beartype
def build_outbox_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> OutboxStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoOutboxStore.from_settings(mongo, client=client)
    return InMemoryOutboxStore(max_attempts=mongo.outbox_max_attempts)


@beartype
def build_outbox_admin_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> OutboxAdminStore:
    store = build_outbox_store(settings, client=client)
    if not isinstance(store, OutboxAdminStore):
        raise TypeError("Outbox store does not implement OutboxAdminStore")
    return store


@beartype
def build_form_submission_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> FormSubmissionStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoFormSubmissionStore.from_settings(mongo, client=client)
    return InMemoryFormSubmissionStore()


@beartype
def build_technician_accountability_repository(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> TechnicianAccountabilityRepository:
    event_store = build_technician_accountability_event_store(settings, client=client)
    return MongoTechnicianAccountabilityRepository(event_store=event_store)


@beartype
def build_technician_accountability_event_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> TechnicianAccountabilityEventStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoTechnicianAccountabilityEventStore.from_settings(mongo, client=client)
    return InMemoryTechnicianAccountabilityEventStore()


@beartype
def build_external_side_effect_registry(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> ExternalSideEffectRegistry:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoExternalSideEffectRegistry.from_settings(mongo, client=client)
    return InMemoryExternalSideEffectRegistry()


@beartype
def build_technician_last_maintenance_projection(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None,
) -> TechnicianLastMaintenanceProjection:
    if client is not None and settings.mongodb.uri:
        return MongoTechnicianLastMaintenanceProjection(
            _collection=client[settings.mongodb.database][
                settings.mongodb.technician_last_maintenance_collection
            ],
        )
    return InMemoryTechnicianLastMaintenanceProjection()


@beartype
def build_maintenance_cooldown_bypass_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MaintenanceCooldownBypassStore:
    if not settings.mongodb.is_configured:
        raise ValueError(
            "MONGODB_URI must be set for maintenance cooldown bypass admin",
        )
    return MongoMaintenanceCooldownBypassStore.from_settings(
        settings.mongodb,
        client=client,
        service_calendar_timezone=settings.service_calendar.zone_info(),
        service_day_end_hour=settings.service_calendar.service_day_end_hour,
    )


@beartype
def build_maintenance_cooldown_bypass_reader(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MaintenanceCooldownBypassReader:
    if client is not None and settings.mongodb.uri:
        return MongoMaintenanceCooldownBypassStore.from_settings(
            settings.mongodb,
            client=client,
            service_calendar_timezone=settings.service_calendar.zone_info(),
            service_day_end_hour=settings.service_calendar.service_day_end_hour,
        )
    return NullMaintenanceCooldownBypassReader()


@beartype
def build_matrix_snapshot_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None,
) -> MatrixPriceSnapshotStore:
    if settings.mongodb.is_configured and client is not None:
        return MongoMatrixPriceSnapshotStore.from_settings(settings.mongodb, client=client)
    return InMemoryMatrixPriceSnapshotStore()
