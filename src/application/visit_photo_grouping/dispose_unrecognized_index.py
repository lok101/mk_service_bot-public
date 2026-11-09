from __future__ import annotations

import logging
from enum import StrEnum
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
    AppendLearnedReference,
    RecordMissingRequiredGroup,
    RelocateBatchIndex,
    require_reserved_catalog_groups,
)
from src.application.visit_photo_review.ports import (
    AcceptedBatch,
    AcceptedBatchReader,
    CatalogUnavailable,
    ReviewCatalogSource,
    ReviewStore,
    load_review_catalog,
)
from src.domain.visit_photo_review import (
    AssignError,
    CatalogInvalid,
    MissingGroupError,
    Result,
    ReviewCatalog,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class DisposePhotoBytesReader(Protocol):
    @beartype
    def get_bytes(self, storage_key: str) -> bytes: ...


class DisposeAction(StrEnum):
    CONTENT = "content"
    TRASH = "trash"
    POOR_QUALITY = "poor_quality"


class DisposeError(StrEnum):
    CATALOG_UNAVAILABLE = "catalog_unavailable"
    BATCH_NOT_ACCEPTED = "batch_not_accepted"
    INDEX_WITHOUT_FILE = "index_without_file"
    INDEX_NOT_IN_UNRECOGNIZED = "index_not_in_unrecognized"
    INVALID_TARGET = "invalid_target"
    RELOCATE_FAILED = "relocate_failed"


class DisposeUnrecognizedIndex:
    @beartype
    def __init__(
        self,
        *,
        catalog: ReviewCatalogSource,
        store: ReviewStore,
        batches: AcceptedBatchReader,
        relocate: RelocateBatchIndex,
        missing: RecordMissingRequiredGroup,
        append_learned: AppendLearnedReference | None = None,
        photo_bytes: DisposePhotoBytesReader | None = None,
        learned_max_per_group: int = 200,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._batches = batches
        self._relocate = relocate
        self._missing = missing
        self._append_learned = append_learned
        self._photo_bytes = photo_bytes
        self._learned_max_per_group = learned_max_per_group

    @beartype
    def execute(
        self,
        batch_id: str,
        index: int,
        action: DisposeAction,
        target_group_id: str | None,
    ) -> Result[None, DisposeError]:
        batch = self._batches.get(batch_id)
        if batch is None:
            self._log_reject(batch_id, DisposeError.BATCH_NOT_ACCEPTED)
            return Result.err(DisposeError.BATCH_NOT_ACCEPTED)

        try:
            catalog = load_review_catalog(self._catalog, machine_id=batch.machine_id)
            require_reserved_catalog_groups(catalog)
        except CatalogUnavailable:
            self._log_reject(batch_id, DisposeError.CATALOG_UNAVAILABLE)
            return Result.err(DisposeError.CATALOG_UNAVAILABLE)
        except CatalogInvalid:
            self._log_reject(batch_id, DisposeError.CATALOG_UNAVAILABLE)
            return Result.err(DisposeError.CATALOG_UNAVAILABLE)

        file_indexes = {item.index for item in batch.files}
        if index not in file_indexes:
            self._log_reject(batch_id, DisposeError.INDEX_WITHOUT_FILE)
            return Result.err(DisposeError.INDEX_WITHOUT_FILE)

        desired = self._desired_target(
            action, target_group_id, catalog_group_ids={group.group_id for group in catalog.groups}
        )
        if isinstance(desired, DisposeError):
            self._log_reject(batch_id, desired)
            return Result.err(desired)

        current_groups = {
            assignment.group_id
            for assignment in self._store.assignments_for_batch(batch_id)
            if index in assignment.indexes
        }
        if self._already_at_desired(current_groups, desired):
            missing_cycle = self._run_missing_cycle_if_unrecognized_empty(batch_id, catalog)
            if missing_cycle.is_err():
                return missing_cycle
            self._log_success(batch_id, index, action, target_group_id)
            return Result.ok(None)

        if UNRECOGNIZED_GROUP_ID not in current_groups:
            self._log_reject(batch_id, DisposeError.INDEX_NOT_IN_UNRECOGNIZED)
            return Result.err(DisposeError.INDEX_NOT_IN_UNRECOGNIZED)

        relocated = self._relocate.execute(batch_id, index, desired)
        if relocated.is_err():
            mapped = self._map_assign_error(relocated.error)
            self._log_reject(batch_id, mapped)
            return Result.err(mapped)

        if action is DisposeAction.CONTENT and desired is not None:
            self._best_effort_append_learned(batch, index, desired)

        missing_cycle = self._run_missing_cycle_if_unrecognized_empty(batch_id, catalog)
        if missing_cycle.is_err():
            return missing_cycle

        self._log_success(batch_id, index, action, target_group_id)
        return Result.ok(None)

    def _best_effort_append_learned(
        self,
        batch: AcceptedBatch,
        index: int,
        target_group_id: str,
    ) -> None:
        if self._append_learned is None or self._photo_bytes is None:
            return
        photo = next((item for item in batch.files if item.index == index), None)
        if photo is None:
            return
        try:
            content = self._photo_bytes.get_bytes(photo.storage_key)
            self._append_learned.execute(
                group_id=target_group_id,
                batch_id=batch.batch_id,
                index=index,
                content=content,
                content_type=photo.content_type,
                max_per_group=self._learned_max_per_group,
            )
        except Exception:
            logger.info(
                "visit_photo_review.reference_append_failed",
                extra={
                    "group_id": target_group_id,
                    "batch_id": batch.batch_id,
                    "index": index,
                    "reason": "append_exception",
                },
            )

    def _desired_target(
        self,
        action: DisposeAction,
        target_group_id: str | None,
        *,
        catalog_group_ids: set[str],
    ) -> str | None | DisposeError:
        if action is DisposeAction.TRASH:
            return None
        if action is DisposeAction.POOR_QUALITY:
            return POOR_QUALITY_GROUP_ID
        if not target_group_id:
            return DisposeError.INVALID_TARGET
        if target_group_id in {UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID}:
            return DisposeError.INVALID_TARGET
        if target_group_id not in catalog_group_ids:
            return DisposeError.INVALID_TARGET
        return target_group_id

    @staticmethod
    def _already_at_desired(current_groups: set[str], desired: str | None) -> bool:
        if desired is None:
            return not current_groups
        return current_groups == {desired}

    def _run_missing_cycle_if_unrecognized_empty(
        self,
        batch_id: str,
        catalog: ReviewCatalog,
    ) -> Result[None, DisposeError]:
        unrecognized = self._store.find_assignment(batch_id, UNRECOGNIZED_GROUP_ID)
        if unrecognized is not None and unrecognized.indexes:
            return Result.ok(None)

        for item in catalog.groups:
            if not item.required:
                continue
            if self._store.find_assignment(batch_id, item.group_id) is not None:
                continue
            recorded = self._missing.execute(batch_id, item.group_id)
            if recorded.is_ok():
                continue
            if recorded.error in {
                MissingGroupError.HAS_ASSIGNMENT,
                MissingGroupError.HAS_HUMAN_RECORD,
            }:
                continue
            if recorded.error is MissingGroupError.CATALOG_UNAVAILABLE:
                self._log_reject(batch_id, DisposeError.CATALOG_UNAVAILABLE)
                return Result.err(DisposeError.CATALOG_UNAVAILABLE)
            self._log_reject(batch_id, DisposeError.RELOCATE_FAILED)
            return Result.err(DisposeError.RELOCATE_FAILED)
        return Result.ok(None)

    @staticmethod
    def _map_assign_error(error: AssignError) -> DisposeError:
        if error is AssignError.CATALOG_UNAVAILABLE:
            return DisposeError.CATALOG_UNAVAILABLE
        if error is AssignError.BATCH_NOT_ACCEPTED:
            return DisposeError.BATCH_NOT_ACCEPTED
        if error is AssignError.INDEX_WITHOUT_FILE:
            return DisposeError.INDEX_WITHOUT_FILE
        if error is AssignError.UNKNOWN_GROUP:
            return DisposeError.INVALID_TARGET
        return DisposeError.RELOCATE_FAILED

    def _log_success(
        self,
        batch_id: str,
        index: int,
        action: DisposeAction,
        target_group_id: str | None,
    ) -> None:
        logger.info(
            "visit_photo_grouping.dispose",
            extra={
                "batch_id": batch_id,
                "index": index,
                "action": action.value,
                "target_group_id": target_group_id,
            },
        )

    def _log_reject(self, batch_id: str, code: DisposeError) -> None:
        logger.info(
            "visit_photo_grouping.dispose rejected",
            extra={"batch_id": batch_id, "code": code.value},
        )
