from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.visit_photo_review.ports import (
    EDITOR_EXCLUDED_GROUP_IDS,
    PHOTO_ONLY_GROUP_IDS,
    PHOTO_ONLY_TITLES,
    AcceptedBatchReader,
    ReviewCatalogSource,
    ReviewStore,
)
from src.domain.calendar import operational_day_window
from src.domain.visit_photo_review import (
    DefectButton,
    GroupAssignment,
    ReviewCatalog,
    ReviewRecord,
)

PAGE_SIZE = 50

QueueViewFilter = Literal["unviewed", "all"]


@beartype
@dataclass(frozen=True, slots=True)
class ReviewQueueFrame:
    batch_id: str
    index: int
    occurred_at: datetime
    machine_id: str
    technician_id: str


@beartype
@dataclass(frozen=True, slots=True)
class ReviewQueueGroup:
    group_id: str
    frames: tuple[ReviewQueueFrame, ...]
    is_missing: bool


@beartype
@dataclass(frozen=True, slots=True)
class ReviewBlockRow:
    batch_id: str
    group_id: str
    indexes: tuple[int, ...]
    occurred_at: datetime
    machine_id: str
    technician_id: str
    has_human_record: bool
    is_missing: bool


@beartype
@dataclass(frozen=True, slots=True)
class ReviewBlockList:
    items: tuple[ReviewBlockRow, ...]
    total: int


@beartype
@dataclass(frozen=True, slots=True)
class AdjacentBlock:
    prev_batch_id: str | None
    prev_group_id: str | None
    next_batch_id: str | None
    next_group_id: str | None


@beartype
@dataclass(frozen=True, slots=True)
class ReviewPhotoRef:
    storage_key: str
    content_type: str


@beartype
@dataclass(frozen=True, slots=True)
class CatalogEditorGroup:
    group_id: str
    title: str
    required: bool
    defects: tuple[DefectButton, ...]
    photo_only: bool


@beartype
@dataclass(frozen=True, slots=True)
class ProblemRow:
    batch_id: str
    group_id: str
    photo_index: int
    occurred_at: datetime
    machine_id: str
    technician_id: str
    group_title: str
    defect_code: str
    defect_label: str


@beartype
@dataclass(frozen=True, slots=True)
class ProblemRowList:
    items: tuple[ProblemRow, ...]
    total: int


@beartype
class ReviewQueries:
    def __init__(
        self,
        catalog: ReviewCatalogSource,
        store: ReviewStore,
        batches: AcceptedBatchReader,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._batches = batches

    def list_blocks(
        self,
        *,
        day: date | None,
        timezone: ZoneInfo,
        day_end_hour: int,
        group_id: str | None,
        machine_id: str | None,
        technician_id: str | None,
        offset: int,
    ) -> ReviewBlockList:
        catalog = self._catalog.load()
        ordered = self._filtered_block_rows(
            catalog,
            day=day,
            timezone=timezone,
            day_end_hour=day_end_hour,
            group_id=group_id,
            machine_id=machine_id,
            technician_id=technician_id,
        )
        total = len(ordered)
        page = ordered[offset : offset + PAGE_SIZE]
        return ReviewBlockList(items=tuple(page), total=total)

    def list_queue_groups(
        self,
        *,
        day: date | None,
        timezone: ZoneInfo,
        day_end_hour: int,
        machine_id: str | None,
        technician_id: str | None,
        view_filter: QueueViewFilter = "unviewed",
    ) -> tuple[ReviewQueueGroup, ...]:
        catalog = self._catalog.load()
        viewed = {(view.batch_id, view.index) for view in self._store.list_frame_views()}
        frames_by_group: dict[str, list[ReviewQueueFrame]] = {}
        for assignment in self._store.list_assignments():
            if not self._matches_queue_filters(
                occurred_at=assignment.occurred_at,
                machine_id=assignment.machine_id,
                technician_id=assignment.technician_id,
                day=day,
                timezone=timezone,
                day_end_hour=day_end_hour,
                filter_machine_id=machine_id,
                filter_technician_id=technician_id,
            ):
                continue
            bucket = frames_by_group.setdefault(assignment.group_id, [])
            for index in assignment.indexes:
                if view_filter == "unviewed" and (assignment.batch_id, index) in viewed:
                    continue
                bucket.append(
                    ReviewQueueFrame(
                        batch_id=assignment.batch_id,
                        index=index,
                        occurred_at=assignment.occurred_at,
                        machine_id=assignment.machine_id,
                        technician_id=assignment.technician_id,
                    )
                )

        groups: list[ReviewQueueGroup] = []
        seen: set[str] = set()
        for group in catalog.groups:
            group_id = group.group_id
            frames = sorted(
                frames_by_group.get(group_id, ()),
                key=lambda frame: (frame.occurred_at, frame.batch_id, frame.index),
            )
            if not frames:
                continue
            groups.append(
                ReviewQueueGroup(
                    group_id=group_id,
                    frames=tuple(frames),
                    is_missing=False,
                )
            )
            seen.add(group_id)

        for group_id, frames in frames_by_group.items():
            if group_id in seen:
                continue
            ordered_frames = sorted(
                frames,
                key=lambda frame: (frame.occurred_at, frame.batch_id, frame.index),
            )
            if not ordered_frames:
                continue
            groups.append(
                ReviewQueueGroup(
                    group_id=group_id,
                    frames=tuple(ordered_frames),
                    is_missing=False,
                )
            )
            seen.add(group_id)

        return tuple(groups)

    def _matches_queue_filters(
        self,
        *,
        occurred_at: datetime,
        machine_id: str,
        technician_id: str,
        day: date | None,
        timezone: ZoneInfo,
        day_end_hour: int,
        filter_machine_id: str | None,
        filter_technician_id: str | None,
    ) -> bool:
        if day is not None:
            start, end = operational_day_window(day, timezone, day_end_hour)
            if not (start <= occurred_at < end):
                return False
        if filter_machine_id is not None and machine_id != filter_machine_id:
            return False
        return filter_technician_id is None or technician_id == filter_technician_id

    def list_problem_rows(
        self,
        *,
        day: date | None,
        timezone: ZoneInfo,
        day_end_hour: int,
        group_id: str | None = None,
        machine_id: str | None = None,
        technician_id: str | None = None,
        defect_query: str | None = None,
        day_raw: str | None = None,
        offset: int = 0,
        page_size: int | None = PAGE_SIZE,
    ) -> ProblemRowList:
        if day_raw is not None and day_raw != "all":
            try:
                day = date.fromisoformat(day_raw)
            except ValueError:
                return ProblemRowList(items=(), total=0)
        elif day_raw == "all":
            day = None

        rows: list[ProblemRow] = []
        for record in self._store.list_records():
            if record.record_kind != "human" or not record.defects:
                continue
            if not record.indexes:
                continue
            if not self._matches_queue_filters(
                occurred_at=record.occurred_at,
                machine_id=record.machine_id,
                technician_id=record.technician_id,
                day=day,
                timezone=timezone,
                day_end_hour=day_end_hour,
                filter_machine_id=machine_id,
                filter_technician_id=technician_id,
            ):
                continue
            if group_id is not None and record.group_id != group_id:
                continue
            photo_index = record.indexes[0]
            for defect in record.defects:
                if defect_query is not None:
                    needle = defect_query.casefold()
                    if (
                        needle not in defect.code.casefold()
                        and needle not in defect.label.casefold()
                    ):
                        continue
                rows.append(
                    ProblemRow(
                        batch_id=record.batch_id,
                        group_id=record.group_id,
                        photo_index=photo_index,
                        occurred_at=record.occurred_at,
                        machine_id=record.machine_id,
                        technician_id=record.technician_id,
                        group_title=record.group_title,
                        defect_code=defect.code,
                        defect_label=defect.label,
                    )
                )
        ordered = sorted(rows, key=lambda row: row.occurred_at, reverse=True)
        total = len(ordered)
        page = ordered[offset:] if page_size is None else ordered[offset : offset + page_size]
        return ProblemRowList(items=tuple(page), total=total)

    def adjacent_block(
        self,
        *,
        current_batch_id: str,
        current_group_id: str,
        day: date | None,
        timezone: ZoneInfo,
        day_end_hour: int,
        group_id: str | None,
        machine_id: str | None,
        technician_id: str | None,
        offset: int,
    ) -> AdjacentBlock:
        _ = offset
        catalog = self._catalog.load()
        ordered = self._filtered_block_rows(
            catalog,
            day=day,
            timezone=timezone,
            day_end_hour=day_end_hour,
            group_id=group_id,
            machine_id=machine_id,
            technician_id=technician_id,
        )
        current_index = next(
            (
                index
                for index, row in enumerate(ordered)
                if row.batch_id == current_batch_id and row.group_id == current_group_id
            ),
            None,
        )
        if current_index is None:
            return AdjacentBlock(
                prev_batch_id=None,
                prev_group_id=None,
                next_batch_id=None,
                next_group_id=None,
            )
        prev_row = ordered[current_index - 1] if current_index > 0 else None
        next_row = ordered[current_index + 1] if current_index + 1 < len(ordered) else None
        return AdjacentBlock(
            prev_batch_id=None if prev_row is None else prev_row.batch_id,
            prev_group_id=None if prev_row is None else prev_row.group_id,
            next_batch_id=None if next_row is None else next_row.batch_id,
            next_group_id=None if next_row is None else next_row.group_id,
        )

    def list_catalog_editor_groups(self) -> tuple[CatalogEditorGroup, ...]:
        catalog = self._catalog.load()
        content = [
            CatalogEditorGroup(
                group_id=group.group_id,
                title=group.title,
                required=group.required,
                defects=group.defects,
                photo_only=False,
            )
            for group in catalog.groups
            if group.group_id not in EDITOR_EXCLUDED_GROUP_IDS
        ]
        content.sort(key=lambda row: row.title)
        service: list[CatalogEditorGroup] = []
        for group_id in PHOTO_ONLY_GROUP_IDS:
            existing = catalog.group(group_id)
            service.append(
                CatalogEditorGroup(
                    group_id=group_id,
                    title=(existing.title if existing is not None else PHOTO_ONLY_TITLES[group_id]),
                    required=False,
                    defects=(),
                    photo_only=True,
                )
            )
        return tuple(content + service)

    def read_photo(self, batch_id: str, index: int) -> ReviewPhotoRef | None:
        allowed = False
        for assignment in self._store.assignments_for_batch(batch_id):
            if index in assignment.indexes:
                allowed = True
                break
        if not allowed:
            for record in self._store.records_for_batch(batch_id):
                if index in record.indexes:
                    allowed = True
                    break
        if not allowed:
            return None
        batch = self._batches.get(batch_id)
        if batch is None:
            return None
        for photo in batch.files:
            if photo.index == index:
                return ReviewPhotoRef(
                    storage_key=photo.storage_key,
                    content_type=photo.content_type,
                )
        return None

    def _filtered_block_rows(
        self,
        catalog: ReviewCatalog,
        *,
        day: date | None,
        timezone: ZoneInfo,
        day_end_hour: int,
        group_id: str | None,
        machine_id: str | None,
        technician_id: str | None,
    ) -> list[ReviewBlockRow]:
        assignment_keys = {
            (item.batch_id, item.group_id) for item in self._store.list_assignments()
        }
        rows = [
            self._row_from_assignment(assignment) for assignment in self._store.list_assignments()
        ]
        for record in self._store.list_records():
            if record.record_kind != "missing":
                continue
            key = (record.batch_id, record.group_id)
            if key in assignment_keys:
                continue
            rows.append(self._row_from_missing(record))
        filtered = self._filter_rows(
            rows,
            day=day,
            timezone=timezone,
            day_end_hour=day_end_hour,
            group_id=group_id,
            machine_id=machine_id,
            technician_id=technician_id,
        )
        return sorted(
            filtered,
            key=lambda row: (
                catalog.order_index(row.group_id),
                row.occurred_at,
                row.batch_id,
            ),
        )

    def _row_from_assignment(self, assignment: GroupAssignment) -> ReviewBlockRow:
        has_human = any(
            record.record_kind == "human" and record.group_id == assignment.group_id
            for record in self._store.records_for_batch(assignment.batch_id)
        )
        return ReviewBlockRow(
            batch_id=assignment.batch_id,
            group_id=assignment.group_id,
            indexes=assignment.indexes,
            occurred_at=assignment.occurred_at,
            machine_id=assignment.machine_id,
            technician_id=assignment.technician_id,
            has_human_record=has_human,
            is_missing=False,
        )

    def _row_from_missing(self, record: ReviewRecord) -> ReviewBlockRow:
        return ReviewBlockRow(
            batch_id=record.batch_id,
            group_id=record.group_id,
            indexes=(),
            occurred_at=record.occurred_at,
            machine_id=record.machine_id,
            technician_id=record.technician_id,
            has_human_record=False,
            is_missing=True,
        )

    def _filter_rows(
        self,
        rows: list[ReviewBlockRow],
        *,
        day: date | None,
        timezone: ZoneInfo,
        day_end_hour: int,
        group_id: str | None,
        machine_id: str | None,
        technician_id: str | None,
    ) -> list[ReviewBlockRow]:
        window: tuple[datetime, datetime] | None = None
        if day is not None:
            window = operational_day_window(day, timezone, day_end_hour)

        result: list[ReviewBlockRow] = []
        for row in rows:
            if window is not None:
                start, end = window
                if not (start <= row.occurred_at < end):
                    continue
            if group_id is not None and row.group_id != group_id:
                continue
            if machine_id is not None and row.machine_id != machine_id:
                continue
            if technician_id is not None and row.technician_id != technician_id:
                continue
            result.append(row)
        return result
