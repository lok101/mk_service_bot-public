from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from beartype import beartype
from pymongo import MongoClient

from src.application.photo_batches.ports import PhotoBatchStore
from src.application.visit_photo_grouping import DisposeUnrecognizedIndex
from src.application.visit_photo_review import (
    AppendLearnedReference,
    AssignBatchGroups,
    ClearReviewRecord,
    RecordMissingRequiredGroup,
    RelocateBatchIndex,
    ReviewQueries,
    SaveReviewRecord,
    UpdateGroupDefects,
    WriteGroupAvatar,
)
from src.application.visit_photo_review.ports import GroupAvatarReader, GroupAvatarWriter
from src.application.visit_photo_review.profile import ResolveVisitPhotoProfile
from src.config.settings import Settings
from src.infrastructure.composition.adapters.visit_photo_profile_lookup import (
    MasterMachineEquipmentLookup,
)
from src.infrastructure.composition.factories import build_master_data_stores
from src.infrastructure.composition.factories.photos import (
    build_photo_batch_store,
    build_photo_storage,
)
from src.infrastructure.mongodb.connection import create_mongo_client
from src.infrastructure.mongodb.visit_photo_profiles import (
    build_mongo_visit_photo_profile_store,
)
from src.infrastructure.visit_photo_grouping.sync_storage import SyncPhotoBytesReader
from src.infrastructure.visit_photo_review import (
    AcceptedBatchReaderAdapter,
    FileReviewCatalog,
    MongoReviewStore,
)
from src.infrastructure.visit_photo_review.mongo_store import ReviewStoreCollection
from src.infrastructure.visit_photo_review.profile_catalog_source import (
    ProfilePreferringReviewCatalog,
)
from src.infrastructure.visit_photo_review.profile_pack_io import (
    ProfilePackPathResolver,
    ProfileResolvingGroupAvatarReader,
    ProfileResolvingGroupAvatarWriter,
    ProfileResolvingLearnedReferenceWriter,
)


@beartype
@dataclass(frozen=True, slots=True)
class VisitPhotoReviewDeps:
    catalog: ProfilePreferringReviewCatalog
    review_queries: ReviewQueries
    assign_batch_groups: AssignBatchGroups
    record_missing_required_group: RecordMissingRequiredGroup
    save_review_record: SaveReviewRecord
    clear_review_record: ClearReviewRecord
    dispose_unrecognized_index: DisposeUnrecognizedIndex
    group_avatar_reader: GroupAvatarReader
    group_avatar_writer: GroupAvatarWriter
    update_group_defects: UpdateGroupDefects
    write_group_avatar: WriteGroupAvatar


@beartype
def build_visit_photo_review_deps(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
    photo_batch_store: PhotoBatchStore | None = None,
) -> VisitPhotoReviewDeps | None:
    if not settings.mongodb.is_configured:
        return None

    mongo_client = client if client is not None else create_mongo_client(settings.mongodb)
    collection = mongo_client[settings.mongodb.database][settings.visit_photo_review.collection]
    store = MongoReviewStore(cast(ReviewStoreCollection, collection))
    # Shared VISIT_PHOTO_REVIEW_CATALOG_PATH is deprecated SoT for coffee/profile path
    # (ADR-0070); kept as read-only fallback when profile resolve misses / non-coffee.
    file_catalog = FileReviewCatalog(settings.visit_photo_review.catalog_path)
    batches_store = (
        photo_batch_store
        if photo_batch_store is not None
        else build_photo_batch_store(settings, client=mongo_client)
    )
    batches = AcceptedBatchReaderAdapter(batches_store)

    def _clock() -> datetime:
        return datetime.now(UTC)

    grouping = settings.visit_photo_grouping
    packs_root = grouping.resolved_packs_root()
    legacy_key = grouping.legacy_default_pack_key()
    legacy_pack = Path(grouping.pack_dir.strip()) if grouping.pack_dir.strip() else None
    resolve_profile = None
    if settings.master_data.enabled:
        master_stores = build_master_data_stores(settings, mongo_client=mongo_client)
        profile_store = build_mongo_visit_photo_profile_store(
            settings.mongodb,
            settings.visit_photo_review,
            client=mongo_client,
        )
        resolve_profile = ResolveVisitPhotoProfile(
            store=profile_store,
            machines=MasterMachineEquipmentLookup(_machines=master_stores.machines),
        )
    catalog = ProfilePreferringReviewCatalog(
        file_catalog,
        resolve_profile,
        profile_strict=settings.visit_photo_review.profile_strict,
    )
    record_missing = RecordMissingRequiredGroup(
        catalog=catalog,
        store=store,
        batches=batches,
        clock=_clock,
    )
    relocate = RelocateBatchIndex(catalog, store, batches)
    path_resolver = ProfilePackPathResolver(
        packs_root=packs_root,
        batches=batches,
        resolve_profile=resolve_profile,
        profile_strict=settings.visit_photo_review.profile_strict,
        legacy_default_pack_key=legacy_key,
        legacy_pack_dir=legacy_pack,
    )
    learned_writer = ProfileResolvingLearnedReferenceWriter(paths=path_resolver)
    append_learned = AppendLearnedReference(learned_writer)
    photo_bytes = SyncPhotoBytesReader(get_bytes_async=build_photo_storage(settings).get_bytes)
    dispose = DisposeUnrecognizedIndex(
        catalog=catalog,
        store=store,
        batches=batches,
        relocate=relocate,
        missing=record_missing,
        append_learned=append_learned,
        photo_bytes=photo_bytes,
        learned_max_per_group=settings.visit_photo_grouping.reference_learned_max_per_group,
    )
    avatar_writer = ProfileResolvingGroupAvatarWriter(paths=path_resolver)
    return VisitPhotoReviewDeps(
        catalog=catalog,
        review_queries=ReviewQueries(catalog=catalog, store=store, batches=batches),
        assign_batch_groups=AssignBatchGroups(
            catalog=catalog,
            store=store,
            batches=batches,
        ),
        record_missing_required_group=record_missing,
        save_review_record=SaveReviewRecord(
            catalog=catalog,
            store=store,
            clock=_clock,
        ),
        clear_review_record=ClearReviewRecord(store=store),
        dispose_unrecognized_index=dispose,
        group_avatar_reader=ProfileResolvingGroupAvatarReader(paths=path_resolver),
        group_avatar_writer=avatar_writer,
        update_group_defects=UpdateGroupDefects(file_catalog),
        write_group_avatar=WriteGroupAvatar(avatar_writer),
    )
