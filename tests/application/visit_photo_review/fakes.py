from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from beartype import beartype

from src.application.visit_photo_review.ports import (
    AcceptedBatch,
    AvatarPackUnavailable,
    CatalogUnavailable,
    GroupAvatar,
    LearnedAppendSkipped,
)
from src.domain.visit_photo_review import (
    CatalogGroup,
    DefectButton,
    FrameView,
    GroupAssignment,
    ReviewCatalog,
    ReviewRecord,
)


def _record_frame_key(record: ReviewRecord) -> int | None:
    if record.record_kind == "missing":
        return None
    if len(record.indexes) == 1:
        return record.indexes[0]
    return None


class MemoryReviewStore:
    def __init__(self) -> None:
        self._assignments: dict[tuple[str, str], GroupAssignment] = {}
        self._records: dict[tuple[str, str, int | None], ReviewRecord] = {}
        self._frame_views: dict[tuple[str, int], FrameView] = {}

    @beartype
    def replace_assignments(
        self,
        batch_id: str,
        assignments: tuple[GroupAssignment, ...],
        *,
        clear_missing_group_ids: tuple[str, ...],
    ) -> None:
        next_assignments = {
            key: value for key, value in self._assignments.items() if key[0] != batch_id
        }
        for assignment in assignments:
            next_assignments[(assignment.batch_id, assignment.group_id)] = assignment

        next_records = dict(self._records)
        for group_id in clear_missing_group_ids:
            key = (batch_id, group_id, None)
            existing = next_records.get(key)
            if existing is not None and existing.record_kind == "missing":
                del next_records[key]

        self._assignments = next_assignments
        self._records = next_records

    @beartype
    def find_assignment(self, batch_id: str, group_id: str) -> GroupAssignment | None:
        return self._assignments.get((batch_id, group_id))

    @beartype
    def assignments_for_batch(self, batch_id: str) -> tuple[GroupAssignment, ...]:
        return tuple(
            item
            for (item_batch_id, _), item in self._assignments.items()
            if item_batch_id == batch_id
        )

    @beartype
    def find_record(self, batch_id: str, group_id: str) -> ReviewRecord | None:
        group_records = [
            record
            for (item_batch_id, item_group_id, _), record in self._records.items()
            if item_batch_id == batch_id and item_group_id == group_id
        ]
        for record in group_records:
            if record.record_kind == "missing":
                return record
        for record in group_records:
            if record.record_kind == "human":
                return record
        return None

    @beartype
    def find_frame_record(
        self, batch_id: str, group_id: str, frame_index: int
    ) -> ReviewRecord | None:
        exact = self._records.get((batch_id, group_id, frame_index))
        if exact is not None and exact.record_kind == "human":
            return exact
        legacy = self._records.get((batch_id, group_id, None))
        if legacy is not None and legacy.record_kind == "human" and frame_index in legacy.indexes:
            return legacy
        return None

    @beartype
    def records_for_batch(self, batch_id: str) -> tuple[ReviewRecord, ...]:
        return tuple(
            item
            for (item_batch_id, _, _), item in self._records.items()
            if item_batch_id == batch_id
        )

    def _detach_frame_from_legacy(self, batch_id: str, group_id: str, frame_index: int) -> None:
        key = (batch_id, group_id, None)
        legacy = self._records.get(key)
        if legacy is None or legacy.record_kind != "human" or frame_index not in legacy.indexes:
            return
        remaining = tuple(index for index in legacy.indexes if index != frame_index)
        if not remaining:
            del self._records[key]
            return
        self._records[key] = replace(legacy, indexes=remaining)

    @beartype
    def save_record(self, record: ReviewRecord) -> None:
        frame_key = _record_frame_key(record)
        if frame_key is not None:
            self._detach_frame_from_legacy(record.batch_id, record.group_id, frame_key)
        self._records[(record.batch_id, record.group_id, frame_key)] = record

    @beartype
    def clear_record(self, batch_id: str, group_id: str, *, frame_index: int | None = None) -> None:
        if frame_index is not None:
            self._records.pop((batch_id, group_id, frame_index), None)
            self._detach_frame_from_legacy(batch_id, group_id, frame_index)
            return
        to_drop = [key for key in self._records if key[0] == batch_id and key[1] == group_id]
        for key in to_drop:
            del self._records[key]

    @beartype
    def list_assignments(self) -> tuple[GroupAssignment, ...]:
        return tuple(self._assignments.values())

    @beartype
    def list_records(self) -> tuple[ReviewRecord, ...]:
        return tuple(self._records.values())

    @beartype
    def save_frame_view(self, view: FrameView) -> None:
        self._frame_views[(view.batch_id, view.index)] = view

    @beartype
    def find_frame_view(self, batch_id: str, index: int) -> FrameView | None:
        return self._frame_views.get((batch_id, index))

    @beartype
    def list_frame_views(self) -> tuple[FrameView, ...]:
        return tuple(self._frame_views.values())


class FixedCatalog:
    def __init__(self, catalog: ReviewCatalog, *, unavailable: bool = False) -> None:
        self._catalog = catalog
        self.unavailable = unavailable

    @beartype
    def load(self) -> ReviewCatalog:
        if self.unavailable:
            raise CatalogUnavailable("catalog unavailable")
        return self._catalog

    @beartype
    def replace_group_defects(
        self,
        group_id: str,
        defects: tuple[DefectButton, ...],
    ) -> None:
        if self.unavailable:
            raise CatalogUnavailable("catalog unavailable")
        groups: list[CatalogGroup] = []
        found = False
        for group in self._catalog.groups:
            if group.group_id == group_id:
                found = True
                groups.append(
                    CatalogGroup(
                        group_id=group.group_id,
                        title=group.title,
                        required=group.required,
                        defects=defects,
                    )
                )
            else:
                groups.append(group)
        if not found:
            msg = f"group not found: {group_id}"
            raise KeyError(msg)
        self._catalog = ReviewCatalog(groups=tuple(groups))


class MemoryGroupAvatarWriter:
    def __init__(self, *, pack_dir_configured: bool = True) -> None:
        self.pack_dir_configured = pack_dir_configured
        self._avatars: dict[str, GroupAvatar] = {}
        self.write_calls: list[tuple[str, bytes, str]] = []

    @beartype
    def write_avatar(self, group_id: str, content: bytes, content_type: str) -> None:
        if not self.pack_dir_configured:
            raise AvatarPackUnavailable("pack dir not configured")
        self.write_calls.append((group_id, content, content_type))
        self._avatars[group_id] = GroupAvatar(content=content, content_type=content_type)

    @beartype
    def read_avatar(self, group_id: str) -> GroupAvatar | None:
        return self._avatars.get(group_id)


class MemoryLearnedReferenceWriter:
    def __init__(
        self,
        *,
        pack_dir_configured: bool = True,
        skip_reason: str | None = None,
        raise_os_error: bool = False,
    ) -> None:
        self.pack_dir_configured = pack_dir_configured
        self.skip_reason = skip_reason
        self.raise_os_error = raise_os_error
        self.append_calls: list[dict[str, object]] = []

    @beartype
    def append_learned(
        self,
        *,
        group_id: str,
        batch_id: str,
        index: int,
        content: bytes,
        content_type: str,
        max_per_group: int,
    ) -> None:
        self.append_calls.append(
            {
                "group_id": group_id,
                "batch_id": batch_id,
                "index": index,
                "content": content,
                "content_type": content_type,
                "max_per_group": max_per_group,
            }
        )
        if not self.pack_dir_configured:
            raise AvatarPackUnavailable("pack dir not configured")
        if self.raise_os_error:
            raise OSError("disk full")
        if self.skip_reason is not None:
            raise LearnedAppendSkipped(self.skip_reason)


class FixedBatches:
    def __init__(self, batch: AcceptedBatch | None) -> None:
        self._batch = batch

    @beartype
    def get(self, batch_id: str) -> AcceptedBatch | None:
        if self._batch is None or self._batch.batch_id != batch_id:
            return None
        return self._batch


class FixedClock:
    def __init__(self, now_value: datetime) -> None:
        self.now_value = now_value

    @beartype
    def now(self) -> datetime:
        return self.now_value
