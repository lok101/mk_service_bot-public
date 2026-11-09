from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from beartype import beartype

from src.application.visit_photo_grouping.ports import (
    GroupClassifier,
    GroupingBatchReader,
    GroupingBatchView,
    GroupingGroup,
    GroupingStoredFile,
    GroupingSuccess,
    GroupingTemporaryFailure,
    MachineReviewParticipation,
)
from src.application.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
    AssignBatchGroups,
    RecordMissingRequiredGroup,
    require_reserved_catalog_groups,
)
from src.application.visit_photo_review.ports import (
    CatalogUnavailable,
    ReviewCatalogSource,
    load_review_catalog,
)
from src.domain.visit_photo_review import (
    AssignError,
    CatalogInvalid,
    MissingGroupError,
    ReviewCatalog,
)


class DeliveryKind(StrEnum):
    SUCCESS = "success"
    RETRY = "retry"
    PERMANENT = "permanent"


class GroupingRetryReason(StrEnum):
    BATCH_MISSING = "batch_missing"
    BATCH_WAITING_HASHES = "batch_waiting_hashes"
    CATALOG_UNAVAILABLE = "catalog_unavailable"
    CATALOG_INVALID = "catalog_invalid"
    CLASSIFIER_TEMPORARY = "classifier_temporary"
    VISIT_PHOTO_PROFILE_MISSING = "visit_photo_profile_missing"
    ASSIGN_CATALOG_UNAVAILABLE = "assign_catalog_unavailable"
    MISSING_CATALOG_UNAVAILABLE = "missing_catalog_unavailable"


@beartype
@dataclass(frozen=True, slots=True)
class GroupingDelivery:
    kind: DeliveryKind
    batch_id: str
    machine_id: str
    reason: GroupingRetryReason | None = None


def _delivery(
    kind: DeliveryKind,
    batch: GroupingBatchView,
    *,
    reason: GroupingRetryReason | None = None,
) -> GroupingDelivery:
    return GroupingDelivery(
        kind=kind,
        batch_id=batch.batch_id,
        machine_id=batch.machine_id,
        reason=reason,
    )


def _response_is_invalid(
    catalog: ReviewCatalog,
    files: tuple[GroupingStoredFile, ...],
    groups: tuple[GroupingGroup, ...],
) -> bool:
    known = {item.index for item in files}
    seen: set[int] = set()
    reserved = {UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID}
    for group in groups:
        if group.group_id in reserved:
            return True
        if catalog.group(group.group_id) is None or not group.indexes:
            return True
        for index in group.indexes:
            if index in seen or index not in known:
                return True
            seen.add(index)
    return False


class GroupAcceptedBatch:
    @beartype
    def __init__(
        self,
        *,
        batches: GroupingBatchReader,
        participation: MachineReviewParticipation,
        classifier: GroupClassifier,
        catalog: ReviewCatalogSource,
        assign: AssignBatchGroups,
        missing: RecordMissingRequiredGroup,
    ) -> None:
        self._batches = batches
        self._participation = participation
        self._classifier = classifier
        self._catalog = catalog
        self._assign = assign
        self._missing = missing

    @beartype
    def execute(self, batch_id: str) -> GroupingDelivery:
        batch = self._batches.get(batch_id)
        if batch is None:
            return GroupingDelivery(
                kind=DeliveryKind.RETRY,
                batch_id=batch_id,
                machine_id="",
                reason=GroupingRetryReason.BATCH_MISSING,
            )
        if batch.status != "accepted":
            return _delivery(DeliveryKind.SUCCESS, batch)
        if not batch.files or any(not item.content_hash for item in batch.files):
            return _delivery(
                DeliveryKind.RETRY,
                batch,
                reason=GroupingRetryReason.BATCH_WAITING_HASHES,
            )
        if not self._participation.include(batch.machine_id):
            return _delivery(DeliveryKind.SUCCESS, batch)
        try:
            catalog = load_review_catalog(self._catalog, machine_id=batch.machine_id)
        except CatalogUnavailable:
            return _delivery(
                DeliveryKind.RETRY,
                batch,
                reason=GroupingRetryReason.CATALOG_UNAVAILABLE,
            )
        try:
            require_reserved_catalog_groups(catalog)
        except CatalogInvalid:
            return _delivery(
                DeliveryKind.RETRY,
                batch,
                reason=GroupingRetryReason.CATALOG_INVALID,
            )
        classified = self._classifier.classify(batch.batch_id, batch.files)
        if isinstance(classified, GroupingTemporaryFailure):
            retry_reason = GroupingRetryReason.CLASSIFIER_TEMPORARY
            if classified.reason_code == GroupingRetryReason.VISIT_PHOTO_PROFILE_MISSING.value:
                retry_reason = GroupingRetryReason.VISIT_PHOTO_PROFILE_MISSING
            return _delivery(
                DeliveryKind.RETRY,
                batch,
                reason=retry_reason,
            )
        if not isinstance(classified, GroupingSuccess):
            return _delivery(DeliveryKind.PERMANENT, batch)
        if _response_is_invalid(catalog, batch.files, classified.groups):
            return _delivery(DeliveryKind.PERMANENT, batch)
        known = {item.index for item in batch.files}
        named = {index for group in classified.groups for index in group.indexes}
        omitted = sorted(index for index in known if index not in named)
        assign_groups: list[tuple[str, tuple[int, ...]]] = [
            (group.group_id, group.indexes) for group in classified.groups
        ]
        if omitted:
            assign_groups.append((UNRECOGNIZED_GROUP_ID, tuple(omitted)))
        if assign_groups:
            assigned = self._assign.execute(batch.batch_id, tuple(assign_groups))
            if assigned.is_err():
                if assigned.error is AssignError.CATALOG_UNAVAILABLE:
                    return _delivery(
                        DeliveryKind.RETRY,
                        batch,
                        reason=GroupingRetryReason.ASSIGN_CATALOG_UNAVAILABLE,
                    )
                return _delivery(DeliveryKind.PERMANENT, batch)
        if omitted:
            return _delivery(DeliveryKind.SUCCESS, batch)
        present = {group_id for group_id, _indexes in assign_groups}
        for item in catalog.groups:
            if not item.required or item.group_id in present:
                continue
            recorded = self._missing.execute(batch.batch_id, item.group_id)
            if recorded.is_ok() or recorded.error is MissingGroupError.HAS_HUMAN_RECORD:
                continue
            if recorded.error is MissingGroupError.CATALOG_UNAVAILABLE:
                return _delivery(
                    DeliveryKind.RETRY,
                    batch,
                    reason=GroupingRetryReason.MISSING_CATALOG_UNAVAILABLE,
                )
            return _delivery(DeliveryKind.PERMANENT, batch)
        return _delivery(DeliveryKind.SUCCESS, batch)
