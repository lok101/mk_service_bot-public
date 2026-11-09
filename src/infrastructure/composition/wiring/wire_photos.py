from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.machine_operations.additional_maintenance import (
    AlwaysDenyAdditionalMaintenance,
)
from src.application.machine_operations.ports import AdditionalMaintenanceAllowed
from src.application.machine_operations.services import RegisterLoadingPhotosService
from src.application.master_data import MasterMachineStore
from src.application.photo_batches.accept import AcceptLoadingPhotosService
from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.application.photo_integrity.notifier_ref import PhotoIntegrityAlertNotifierRef
from src.application.visit_photo_review.profile import ResolveVisitPhotoProfile
from src.config.settings import Settings
from src.infrastructure.composition.adapters.closable_extra_additional_maintenance import (
    ClosableExtraAdditionalMaintenance,
)
from src.infrastructure.composition.adapters.visit_photo_profile_lookup import (
    MasterMachineEquipmentLookup,
    ResolveVisitPhotoProfileCueAdapter,
)
from src.infrastructure.composition.bundles.machine_ops import MachineOpsBundle
from src.infrastructure.composition.bundles.photos import PhotoPipelineBundle
from src.infrastructure.composition.factories import (
    build_photo_batch_store,
    build_photo_storage,
    build_service_visit_store,
)
from src.infrastructure.composition.factories.micromarket_loading import (
    MasterDataMachineKindLookup,
)
from src.infrastructure.mongodb.visit_photo_profiles import (
    build_mongo_visit_photo_profile_store,
)
from src.infrastructure.photo_batches.stubs import StubTelegramPhotoDownloader
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier
from src.interfaces.telegram.loading_photos_notifier import NoOpLoadingPhotosChatNotifier
from src.interfaces.telegram.photo_integrity_alert_notifier import NoOpPhotoIntegrityAlertNotifier


@beartype
@dataclass(frozen=True, slots=True)
class _StrMachineKindLookup:
    """Adapts master-data kind lookup to str | None for photo_batches (no BC edge)."""

    _inner: MasterDataMachineKindLookup

    @beartype
    def kind_of(self, machine_code: str) -> str | None:
        kind = self._inner.kind_of(machine_code)
        if kind is None:
            return None
        return str(kind)


@beartype
def wire_photos(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
    machine_ops: MachineOpsBundle,
    machines: MasterMachineStore,
) -> PhotoPipelineBundle:
    photo_batch_store = build_photo_batch_store(settings, client=mongo_client)
    additional_maintenance: AdditionalMaintenanceAllowed
    if settings.mongodb.is_configured:
        additional_maintenance = ClosableExtraAdditionalMaintenance(
            build_service_visit_store(settings, client=mongo_client),
        )
    else:
        additional_maintenance = AlwaysDenyAdditionalMaintenance()
    register_loading_photos = RegisterLoadingPhotosService(
        executor=machine_ops.executor,
        machine_operations=machine_ops.repository,
        last_maintenance_reader=machine_ops.technician_last_maintenance,
        maintenance_cooldown_minutes=settings.service_rules.maintenance_cooldown_minutes,
        bypass_reader=machine_ops.maintenance_cooldown_bypass,
        service_calendar_timezone=machine_ops.service_calendar_timezone,
        additional_maintenance=additional_maintenance,
        inventory_gate=machine_ops.inventory_gate,
    )
    kind_lookup = _StrMachineKindLookup(
        MasterDataMachineKindLookup(_machines=machines),
    )
    profile_lookup = None
    if settings.mongodb.is_configured:
        profile_store = build_mongo_visit_photo_profile_store(
            settings.mongodb,
            settings.visit_photo_review,
            client=mongo_client,
        )
        profile_lookup = ResolveVisitPhotoProfileCueAdapter(
            resolve=ResolveVisitPhotoProfile(
                store=profile_store,
                machines=MasterMachineEquipmentLookup(_machines=machines),
            ),
            profile_strict=settings.visit_photo_review.profile_strict,
        )
    return PhotoPipelineBundle(
        batch_store=photo_batch_store,
        storage=build_photo_storage(settings),
        accept_loading_photos=AcceptLoadingPhotosService(
            photo_batch_store=photo_batch_store,
            register_loading_photos=register_loading_photos,
            loading_photos_min_count=settings.service_rules.loading_photos_min_count,
            loading_photos_max_count=settings.service_rules.loading_photos_max_count,
            machine_kind_lookup=kind_lookup,
            profile_lookup=profile_lookup,
            profile_strict=settings.visit_photo_review.profile_strict,
        ),
        downloader_ref=PhotoDownloaderRef(StubTelegramPhotoDownloader()),
        loading_photos_notifier_ref=LoadingPhotosChatNotifierRef(
            NoOpLoadingPhotosChatNotifier(),
        ),
        integrity_alert_notifier_ref=PhotoIntegrityAlertNotifierRef(
            NoOpPhotoIntegrityAlertNotifier(),
        ),
        form_workflow_notifier_ref=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
    )
