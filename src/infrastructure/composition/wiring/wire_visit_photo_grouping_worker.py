from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from beartype import beartype

from src.application.visit_photo_grouping import VISIT_PHOTO_GROUPING_HANDLER_ID
from src.application.visit_photo_review.profile import ResolveVisitPhotoProfile
from src.config.settings import Settings
from src.config.visit_photo_grouping import require_grouping_classifier
from src.infrastructure.composition.adapters.visit_photo_profile_lookup import (
    MasterMachineEquipmentLookup,
)
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.factories import (
    build_master_data_stores,
    build_outbox_store,
    build_photo_batch_store,
    build_photo_storage,
)
from src.infrastructure.composition.factories.visit_photo_review import (
    build_visit_photo_review_deps,
)
from src.infrastructure.composition.visit_photo_grouping_worker_container import (
    VisitPhotoGroupingWorkerContainer,
)
from src.infrastructure.mongodb.visit_photo_profiles import (
    build_mongo_visit_photo_profile_store,
)
from src.infrastructure.outbox import OutboxDomainEventPublisher, OutboxProcessorRegistry
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.visit_photo_grouping import (
    OpenClipGroupClassifier,
    build_visit_photo_grouping_handler,
    register_visit_photo_grouping,
)
from src.infrastructure.visit_photo_grouping.openclip_classifier import (
    ImageBytesEncoder,
    build_open_clip_encoder,
    open_clip_encoder_id,
)
from src.infrastructure.visit_photo_grouping.profile_aware_classifier import (
    ProfileAwareGroupClassifier,
)
from src.infrastructure.visit_photo_grouping.sync_storage import SyncPhotoBytesReader
from src.infrastructure.visit_photo_grouping.worker_runtime import (
    VisitPhotoGroupingWorkerRuntime,
)


@beartype
def wire_visit_photo_grouping_worker(
    settings: Settings,
    *,
    persistence: PersistenceBundle,
    encoder: ImageBytesEncoder | None = None,
) -> VisitPhotoGroupingWorkerContainer:
    grouping = settings.visit_photo_grouping
    processing = grouping.enabled and grouping.worker_enabled
    mongo_client = persistence.mongo_client
    extra_closers: tuple[Callable[[], None], ...] = ()
    outbox_processors: OutboxProcessorRegistry | None = None
    outbox_worker: OutboxWorker | None = None

    if processing:
        if mongo_client is None or not settings.mongodb.is_configured:
            raise ValueError(
                "VISIT_PHOTO_GROUPING_WORKER_ENABLED=true with grouping enabled "
                "requires a configured MongoDB client",
            )
        resolved_encoder = (
            encoder
            if encoder is not None
            else build_open_clip_encoder(
                weights_path=grouping.weights_path,
            )
        )
        photo_storage = build_photo_storage(settings)
        sync_storage = SyncPhotoBytesReader(get_bytes_async=photo_storage.get_bytes)
        packs_root = grouping.resolved_packs_root()
        if packs_root is None:
            raise ValueError(
                "VISIT_PHOTO_GROUPING_PACKS_ROOT (or legacy PACK_DIR) required "
                "when grouping worker is enabled",
            )
        encoder_id = open_clip_encoder_id(weights_path=grouping.weights_path)

        def _build_openclip(pack_dir: Path) -> OpenClipGroupClassifier:
            return OpenClipGroupClassifier(
                pack_dir=pack_dir,
                storage=sync_storage,
                encoder=resolved_encoder,
                encoder_id=encoder_id,
            )

        photo_batch_store = build_photo_batch_store(settings, client=mongo_client)
        master_stores = (
            build_master_data_stores(settings, mongo_client=mongo_client)
            if settings.master_data.enabled
            else None
        )
        resolve_profile = None
        if master_stores is not None:
            profile_store = build_mongo_visit_photo_profile_store(
                settings.mongodb,
                settings.visit_photo_review,
                client=mongo_client,
            )
            resolve_profile = ResolveVisitPhotoProfile(
                store=profile_store,
                machines=MasterMachineEquipmentLookup(_machines=master_stores.machines),
            )

        def _machine_id_for_batch(batch_id: str) -> str | None:
            from src.domain.ids import BatchId

            batch = photo_batch_store.get_by_batch_id(BatchId(batch_id))
            if batch is None:
                return None
            return batch.machine_id.value

        classifier = ProfileAwareGroupClassifier(
            packs_root=packs_root,
            machine_id_for_batch=_machine_id_for_batch,
            resolve_profile=resolve_profile,
            profile_strict=settings.visit_photo_review.profile_strict,
            legacy_default_pack_key=grouping.legacy_default_pack_key(),
            build_classifier=_build_openclip,
        )
        checked = require_grouping_classifier(True, classifier)
        review_deps = build_visit_photo_review_deps(
            settings,
            client=mongo_client,
            photo_batch_store=photo_batch_store,
        )
        if review_deps is None:
            raise ValueError(
                "visit photo review command dependencies are required when "
                "VISIT_PHOTO_GROUPING_ENABLED=true",
            )
        # Shared catalog_path deprecated for coffee/profile path (ADR-0070).
        catalog = review_deps.catalog
        handler = build_visit_photo_grouping_handler(
            enabled=True,
            photo_batch_store=photo_batch_store,
            machines=(master_stores.machines if master_stores is not None else None),
            classifier=checked,
            catalog=catalog,
            assign=review_deps.assign_batch_groups,
            missing=review_deps.record_missing_required_group,
            not_ready_retry_minutes=grouping.not_ready_retry_minutes,
            not_ready_max_attempts=grouping.not_ready_max_attempts,
        )
        outbox_store = build_outbox_store(settings, client=mongo_client)
        processors = OutboxProcessorRegistry()
        publisher = OutboxDomainEventPublisher(store=outbox_store)
        register_visit_photo_grouping(
            publisher=publisher,
            processors=processors,
            enabled=True,
            handler=handler,
        )
        assert processors.is_registered(VISIT_PHOTO_GROUPING_HANDLER_ID)
        outbox_processors = processors
        outbox_worker = OutboxWorker(
            store=outbox_store,
            processors=processors,
            poll_interval_seconds=settings.mongodb.outbox_poll_interval_seconds,
        )

    runtime = VisitPhotoGroupingWorkerRuntime(
        enabled=grouping.worker_enabled,
        outbox_worker=outbox_worker,
    )
    return VisitPhotoGroupingWorkerContainer(
        runtime=runtime,
        persistence=persistence,
        extra_closers=extra_closers,
        outbox_processors=outbox_processors,
    )


__all__ = ("wire_visit_photo_grouping_worker",)
