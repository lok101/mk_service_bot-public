from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Never

from beartype import beartype

from src.application.visit_photo_review.defect_slug import defect_code_from_label
from src.application.visit_photo_review.ports import (
    PHOTO_ONLY_GROUP_IDS,
    AcceptedBatchReader,
    AvatarPackUnavailable,
    CatalogUnavailable,
    GroupAvatarWriter,
    LearnedAppendSkipped,
    LearnedReferenceWriter,
    ReviewCatalogSource,
    ReviewCatalogWriter,
    ReviewStore,
    load_review_catalog,
)
from src.domain.visit_photo_review import (
    AssignError,
    DefectButton,
    DefectMark,
    FrameView,
    GroupAssignment,
    MissingGroupError,
    Result,
    ReviewRecord,
    SaveError,
)

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_WEBP_HEADER = (b"RIFF", b"WEBP")
_PHOTO_ONLY_GROUP_ID_SET = frozenset(PHOTO_ONLY_GROUP_IDS)


class UpdateGroupDefectsError(StrEnum):
    PHOTO_ONLY_GROUP = "photo_only_group"
    DUPLICATE_CODE = "duplicate_code"
    UNKNOWN_GROUP = "unknown_group"


class WriteGroupAvatarError(StrEnum):
    PACK_DIR_UNAVAILABLE = "pack_dir_unavailable"
    INVALID_IMAGE = "invalid_image"
    UNSAFE_GROUP_ID = "unsafe_group_id"


class AppendLearnedReferenceError(StrEnum):
    PACK_UNAVAILABLE = "pack_unavailable"
    SKIP_CAP = "skip_cap"
    SKIP_DUP = "skip_dup"
    INVALID = "invalid"


logger = logging.getLogger(__name__)


class AssignBatchGroups:
    @beartype
    def __init__(
        self,
        catalog: ReviewCatalogSource,
        store: ReviewStore,
        batches: AcceptedBatchReader,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._batches = batches

    @beartype
    def execute(
        self,
        batch_id: str,
        groups: tuple[tuple[str, tuple[int, ...]], ...],
    ) -> Result[None, AssignError]:
        batch = self._batches.get(batch_id)
        if batch is None:
            self._log_reject(batch_id, "")
            return Result.err(AssignError.BATCH_NOT_ACCEPTED)

        try:
            catalog = load_review_catalog(self._catalog, machine_id=batch.machine_id)
        except CatalogUnavailable:
            self._log_reject(batch_id, "")
            return Result.err(AssignError.CATALOG_UNAVAILABLE)

        file_indexes = {item.index for item in batch.files}
        seen_indexes: set[int] = set()
        assignments: list[GroupAssignment] = []

        for group_id, indexes in groups:
            if catalog.group(group_id) is None:
                self._log_reject(batch_id, group_id)
                return Result.err(AssignError.UNKNOWN_GROUP)
            if not indexes:
                self._log_reject(batch_id, group_id)
                return Result.err(AssignError.EMPTY_GROUP)
            for index in indexes:
                if index in seen_indexes:
                    self._log_reject(batch_id, group_id)
                    return Result.err(AssignError.DUPLICATE_INDEX)
                seen_indexes.add(index)
                if index not in file_indexes:
                    self._log_reject(batch_id, group_id)
                    return Result.err(AssignError.INDEX_WITHOUT_FILE)
            assignments.append(
                GroupAssignment(
                    batch_id=batch_id,
                    group_id=group_id,
                    indexes=indexes,
                    machine_id=batch.machine_id,
                    technician_id=batch.technician_id,
                    occurred_at=batch.occurred_at,
                )
            )

        clear_missing_group_ids = tuple(group_id for group_id, _ in groups)
        self._store.replace_assignments(
            batch_id,
            tuple(assignments),
            clear_missing_group_ids=clear_missing_group_ids,
        )
        return Result.ok(None)

    def _log_reject(self, batch_id: str, group_id: str) -> None:
        logger.info(
            "visit_photo_review.assign rejected",
            extra={"batch_id": batch_id, "group_id": group_id},
        )


class RelocateBatchIndex:
    @beartype
    def __init__(
        self,
        catalog: ReviewCatalogSource,
        store: ReviewStore,
        batches: AcceptedBatchReader,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._batches = batches

    @beartype
    def execute(
        self,
        batch_id: str,
        index: int,
        target_group_id: str | None,
    ) -> Result[None, AssignError]:
        batch = self._batches.get(batch_id)
        if batch is None:
            self._log_reject(batch_id, target_group_id or "")
            return Result.err(AssignError.BATCH_NOT_ACCEPTED)

        try:
            catalog = load_review_catalog(self._catalog, machine_id=batch.machine_id)
        except CatalogUnavailable:
            self._log_reject(batch_id, target_group_id or "")
            return Result.err(AssignError.CATALOG_UNAVAILABLE)

        file_indexes = {item.index for item in batch.files}
        if index not in file_indexes:
            self._log_reject(batch_id, target_group_id or "")
            return Result.err(AssignError.INDEX_WITHOUT_FILE)

        if target_group_id is not None and catalog.group(target_group_id) is None:
            self._log_reject(batch_id, target_group_id)
            return Result.err(AssignError.UNKNOWN_GROUP)

        new_assignments: list[GroupAssignment] = []
        target_found = False
        for assignment in self._store.assignments_for_batch(batch_id):
            remaining = tuple(i for i in assignment.indexes if i != index)
            if assignment.group_id == target_group_id:
                target_found = True
                merged = tuple(sorted({*remaining, index}))
                new_assignments.append(
                    GroupAssignment(
                        batch_id=batch_id,
                        group_id=assignment.group_id,
                        indexes=merged,
                        machine_id=batch.machine_id,
                        technician_id=batch.technician_id,
                        occurred_at=batch.occurred_at,
                    )
                )
            elif remaining:
                new_assignments.append(
                    GroupAssignment(
                        batch_id=batch_id,
                        group_id=assignment.group_id,
                        indexes=remaining,
                        machine_id=assignment.machine_id,
                        technician_id=assignment.technician_id,
                        occurred_at=assignment.occurred_at,
                    )
                )

        if target_group_id is not None and not target_found:
            new_assignments.append(
                GroupAssignment(
                    batch_id=batch_id,
                    group_id=target_group_id,
                    indexes=(index,),
                    machine_id=batch.machine_id,
                    technician_id=batch.technician_id,
                    occurred_at=batch.occurred_at,
                )
            )

        clear_missing_group_ids = (target_group_id,) if target_group_id is not None else ()
        self._store.replace_assignments(
            batch_id,
            tuple(new_assignments),
            clear_missing_group_ids=clear_missing_group_ids,
        )
        return Result.ok(None)

    def _log_reject(self, batch_id: str, group_id: str) -> None:
        logger.info(
            "visit_photo_review.relocate rejected",
            extra={"batch_id": batch_id, "group_id": group_id},
        )


class RecordMissingRequiredGroup:
    @beartype
    def __init__(
        self,
        catalog: ReviewCatalogSource,
        store: ReviewStore,
        batches: AcceptedBatchReader,
        clock: Callable[[], datetime],
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._batches = batches
        self._clock = clock

    @beartype
    def execute(self, batch_id: str, group_id: str) -> Result[ReviewRecord, MissingGroupError]:
        batch = self._batches.get(batch_id)
        if batch is None:
            self._log_reject(batch_id, group_id)
            return Result.err(MissingGroupError.BATCH_NOT_ACCEPTED)

        try:
            catalog = load_review_catalog(self._catalog, machine_id=batch.machine_id)
        except CatalogUnavailable:
            self._log_reject(batch_id, group_id)
            return Result.err(MissingGroupError.CATALOG_UNAVAILABLE)

        group = catalog.group(group_id)
        if group is None or not group.required:
            self._log_reject(batch_id, group_id)
            return Result.err(MissingGroupError.GROUP_NOT_REQUIRED)

        if self._store.find_assignment(batch_id, group_id) is not None:
            self._log_reject(batch_id, group_id)
            return Result.err(MissingGroupError.HAS_ASSIGNMENT)

        existing = self._store.find_record(batch_id, group_id)
        if existing is not None and existing.record_kind == "human":
            self._log_reject(batch_id, group_id)
            return Result.err(MissingGroupError.HAS_HUMAN_RECORD)
        if existing is not None and existing.record_kind == "missing":
            return Result.ok(existing)

        record = ReviewRecord(
            batch_id=batch_id,
            group_id=group_id,
            record_kind="missing",
            indexes=(),
            defects=(),
            system_error=False,
            comment="",
            creator_kind="system",
            actor_user_id=None,
            saved_at=self._clock(),
            group_title=group.title,
            machine_id=batch.machine_id,
            technician_id=batch.technician_id,
            occurred_at=batch.occurred_at,
        )
        self._store.save_record(record)
        return Result.ok(record)

    def _log_reject(self, batch_id: str, group_id: str) -> None:
        logger.info(
            "visit_photo_review.missing_required_group rejected",
            extra={"batch_id": batch_id, "group_id": group_id},
        )


class SaveReviewRecord:
    @beartype
    def __init__(
        self,
        catalog: ReviewCatalogSource,
        store: ReviewStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._clock = clock

    @beartype
    def execute(
        self,
        *,
        actor_user_id: str,
        batch_id: str,
        group_id: str,
        defect_codes: tuple[str, ...],
        system_error: bool,
        comment: str,
        frame_index: int | None = None,
    ) -> Result[ReviewRecord, SaveError]:
        assignment = self._store.find_assignment(batch_id, group_id)
        if assignment is None or not assignment.indexes:
            self._log_reject(batch_id, group_id)
            return Result.err(SaveError.NO_LIVE_ASSIGNMENT)

        try:
            catalog = load_review_catalog(self._catalog, machine_id=assignment.machine_id)
        except CatalogUnavailable:
            self._log_reject(batch_id, group_id)
            return Result.err(SaveError.CATALOG_UNAVAILABLE)

        if frame_index is not None and frame_index not in assignment.indexes:
            self._log_reject(batch_id, group_id)
            return Result.err(SaveError.INVALID_FRAME_INDEX)

        if not defect_codes and not system_error:
            self._log_reject(batch_id, group_id)
            return Result.err(SaveError.NO_MARKS)

        previous = (
            self._store.find_frame_record(batch_id, group_id, frame_index)
            if frame_index is not None
            else self._store.find_record(batch_id, group_id)
        )
        previous_labels = (
            {mark.code: mark.label for mark in previous.defects} if previous is not None else {}
        )
        catalog_group = catalog.group(group_id)
        catalog_labels = (
            {button.code: button.label for button in catalog_group.defects}
            if catalog_group is not None
            else {}
        )

        defects: list[DefectMark] = []
        for code in defect_codes:
            if code in catalog_labels:
                defects.append(DefectMark(code=code, label=catalog_labels[code]))
            elif code in previous_labels:
                defects.append(DefectMark(code=code, label=previous_labels[code]))
            else:
                self._log_reject(batch_id, group_id)
                return Result.err(SaveError.UNKNOWN_DEFECT)

        if catalog_group is not None:
            group_title = catalog_group.title
        elif previous is not None:
            group_title = previous.group_title
        else:
            group_title = group_id

        indexes = (frame_index,) if frame_index is not None else assignment.indexes
        record = ReviewRecord(
            batch_id=batch_id,
            group_id=group_id,
            record_kind="human",
            indexes=indexes,
            defects=tuple(defects),
            system_error=system_error,
            comment=comment,
            creator_kind="human",
            actor_user_id=actor_user_id,
            saved_at=self._clock(),
            group_title=group_title,
            machine_id=assignment.machine_id,
            technician_id=assignment.technician_id,
            occurred_at=assignment.occurred_at,
        )
        self._store.save_record(record)
        return Result.ok(record)

    def _log_reject(self, batch_id: str, group_id: str) -> None:
        logger.info(
            "visit_photo_review.save rejected",
            extra={"batch_id": batch_id, "group_id": group_id},
        )


class ClearReviewRecord:
    @beartype
    def __init__(self, store: ReviewStore) -> None:
        self._store = store

    @beartype
    def execute(
        self, batch_id: str, group_id: str, *, frame_index: int | None = None
    ) -> Result[None, Never]:
        self._store.clear_record(batch_id, group_id, frame_index=frame_index)
        return Result.ok(None)


class RecordFrameView:
    @beartype
    def __init__(self, store: ReviewStore, clock: Callable[[], datetime]) -> None:
        self._store = store
        self._clock = clock

    @beartype
    def execute(self, *, batch_id: str, index: int, actor_user_id: str) -> FrameView:
        existing = self._store.find_frame_view(batch_id, index)
        if existing is not None:
            return existing
        view = FrameView(
            batch_id=batch_id,
            index=index,
            actor_user_id=actor_user_id,
            viewed_at=self._clock(),
        )
        self._store.save_frame_view(view)
        return view


class UpdateGroupDefects:
    @beartype
    def __init__(self, catalog: ReviewCatalogWriter) -> None:
        self._catalog = catalog

    @beartype
    def execute(
        self,
        group_id: str,
        rows: tuple[tuple[str, str], ...],
    ) -> Result[None, UpdateGroupDefectsError]:
        if group_id in _PHOTO_ONLY_GROUP_ID_SET:
            return Result.err(UpdateGroupDefectsError.PHOTO_ONLY_GROUP)

        catalog = self._catalog.load()
        group = catalog.group(group_id)
        if group is None:
            return Result.err(UpdateGroupDefectsError.UNKNOWN_GROUP)

        defects: list[DefectButton] = []
        seen_codes: set[str] = set()
        for raw_code, raw_label in rows:
            label = raw_label.strip()
            if not label:
                continue
            code = raw_code.strip() or defect_code_from_label(label)
            if code in seen_codes:
                return Result.err(UpdateGroupDefectsError.DUPLICATE_CODE)
            seen_codes.add(code)
            defects.append(DefectButton(code=code, label=label))

        self._catalog.replace_group_defects(group_id, tuple(defects))
        return Result.ok(None)


def _is_supported_image(content: bytes) -> bool:
    if content.startswith(_JPEG_MAGIC):
        return True
    if content.startswith(_PNG_MAGIC):
        return True
    return (
        len(content) >= 12
        and content.startswith(_WEBP_HEADER[0])
        and content[8:12] == _WEBP_HEADER[1]
    )


def _is_safe_group_id(group_id: str) -> bool:
    if not group_id:
        return False
    return "/" not in group_id and "\\" not in group_id and ".." not in group_id


class WriteGroupAvatar:
    @beartype
    def __init__(self, writer: GroupAvatarWriter) -> None:
        self._writer = writer

    @beartype
    def execute(
        self,
        *,
        group_id: str,
        content: bytes,
        content_type: str,
    ) -> Result[None, WriteGroupAvatarError]:
        if not _is_safe_group_id(group_id):
            return Result.err(WriteGroupAvatarError.UNSAFE_GROUP_ID)
        if not content or not _is_supported_image(content):
            return Result.err(WriteGroupAvatarError.INVALID_IMAGE)
        try:
            self._writer.write_avatar(group_id, content, content_type)
        except AvatarPackUnavailable:
            return Result.err(WriteGroupAvatarError.PACK_DIR_UNAVAILABLE)
        return Result.ok(None)


class AppendLearnedReference:
    @beartype
    def __init__(self, writer: LearnedReferenceWriter) -> None:
        self._writer = writer

    @beartype
    def execute(
        self,
        *,
        group_id: str,
        batch_id: str,
        index: int,
        content: bytes,
        content_type: str,
        max_per_group: int,
    ) -> Result[None, AppendLearnedReferenceError]:
        if not _is_safe_group_id(group_id) or not batch_id or index < 0:
            self._log_failed(group_id, batch_id, index, "invalid")
            return Result.err(AppendLearnedReferenceError.INVALID)
        if not content or not _is_supported_image(content):
            self._log_failed(group_id, batch_id, index, "invalid_image")
            return Result.err(AppendLearnedReferenceError.INVALID)
        try:
            self._writer.append_learned(
                group_id=group_id,
                batch_id=batch_id,
                index=index,
                content=content,
                content_type=content_type,
                max_per_group=max_per_group,
            )
        except AvatarPackUnavailable:
            self._log_failed(group_id, batch_id, index, "pack_unavailable")
            return Result.err(AppendLearnedReferenceError.PACK_UNAVAILABLE)
        except LearnedAppendSkipped as skipped:
            if skipped.reason == "skip_cap":
                logger.info(
                    "visit_photo_review.reference_append_skipped_cap",
                    extra={
                        "group_id": group_id,
                        "batch_id": batch_id,
                        "index": index,
                    },
                )
                return Result.err(AppendLearnedReferenceError.SKIP_CAP)
            if skipped.reason == "skip_dup":
                logger.info(
                    "visit_photo_review.reference_append_skipped_dup",
                    extra={
                        "group_id": group_id,
                        "batch_id": batch_id,
                        "index": index,
                    },
                )
                return Result.err(AppendLearnedReferenceError.SKIP_DUP)
            self._log_failed(group_id, batch_id, index, skipped.reason)
            return Result.err(AppendLearnedReferenceError.INVALID)
        except ValueError:
            self._log_failed(group_id, batch_id, index, "unsafe_group_id")
            return Result.err(AppendLearnedReferenceError.INVALID)
        except OSError as exc:
            self._log_failed(group_id, batch_id, index, str(exc))
            return Result.err(AppendLearnedReferenceError.PACK_UNAVAILABLE)
        logger.info(
            "visit_photo_review.reference_append_ok",
            extra={"group_id": group_id, "batch_id": batch_id, "index": index},
        )
        return Result.ok(None)

    def _log_failed(self, group_id: str, batch_id: str, index: int, reason: str) -> None:
        logger.info(
            "visit_photo_review.reference_append_failed",
            extra={
                "group_id": group_id,
                "batch_id": batch_id,
                "index": index,
                "reason": reason,
            },
        )
