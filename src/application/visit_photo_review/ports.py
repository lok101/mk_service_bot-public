from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    TRASH_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
    DefectButton,
    FrameView,
    GroupAssignment,
    ReviewCatalog,
    ReviewRecord,
    service_group_title,
)

PHOTO_ONLY_GROUP_IDS = (POOR_QUALITY_GROUP_ID, TRASH_GROUP_ID)
PHOTO_ONLY_TITLES = {
    group_id: (service_group_title(group_id) or group_id) for group_id in PHOTO_ONLY_GROUP_IDS
}
EDITOR_EXCLUDED_GROUP_IDS = frozenset(
    {UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID, TRASH_GROUP_ID}
)


@beartype
@dataclass(frozen=True, slots=True)
class AcceptedPhotoFile:
    index: int
    content_type: str
    storage_key: str


@beartype
@dataclass(frozen=True, slots=True)
class AcceptedBatch:
    batch_id: str
    machine_id: str
    technician_id: str
    occurred_at: datetime
    files: tuple[AcceptedPhotoFile, ...]


@runtime_checkable
class AcceptedBatchReader(Protocol):
    @beartype
    def get(self, batch_id: str) -> AcceptedBatch | None: ...


class CatalogUnavailable(Exception):
    """Review catalog cannot be loaded at call time."""


class AvatarPackUnavailable(Exception):
    """Group avatar pack directory is not configured or not writable."""


@runtime_checkable
class ReviewCatalogSource(Protocol):
    @beartype
    def load(self) -> ReviewCatalog: ...


@runtime_checkable
class MachineScopedReviewCatalogSource(ReviewCatalogSource, Protocol):
    @beartype
    def load_for_machine(self, machine_id: str) -> ReviewCatalog: ...


@beartype
def load_review_catalog(
    source: ReviewCatalogSource,
    *,
    machine_id: str | None = None,
) -> ReviewCatalog:
    """Load catalog; prefer per-machine profile projection when the source supports it."""
    if machine_id is not None and isinstance(source, MachineScopedReviewCatalogSource):
        return source.load_for_machine(machine_id)
    return source.load()


@runtime_checkable
class ReviewCatalogWriter(Protocol):
    @beartype
    def load(self) -> ReviewCatalog: ...

    @beartype
    def replace_group_defects(
        self,
        group_id: str,
        defects: tuple[DefectButton, ...],
    ) -> None: ...


@runtime_checkable
class ReviewStore(Protocol):
    @beartype
    def replace_assignments(
        self,
        batch_id: str,
        assignments: tuple[GroupAssignment, ...],
        *,
        clear_missing_group_ids: tuple[str, ...],
    ) -> None: ...

    @beartype
    def find_assignment(self, batch_id: str, group_id: str) -> GroupAssignment | None: ...

    @beartype
    def assignments_for_batch(self, batch_id: str) -> tuple[GroupAssignment, ...]: ...

    @beartype
    def find_record(self, batch_id: str, group_id: str) -> ReviewRecord | None: ...

    @beartype
    def find_frame_record(
        self, batch_id: str, group_id: str, frame_index: int
    ) -> ReviewRecord | None: ...

    @beartype
    def records_for_batch(self, batch_id: str) -> tuple[ReviewRecord, ...]: ...

    @beartype
    def save_record(self, record: ReviewRecord) -> None: ...

    @beartype
    def clear_record(
        self, batch_id: str, group_id: str, *, frame_index: int | None = None
    ) -> None: ...

    @beartype
    def list_assignments(self) -> tuple[GroupAssignment, ...]: ...

    @beartype
    def list_records(self) -> tuple[ReviewRecord, ...]: ...

    @beartype
    def save_frame_view(self, view: FrameView) -> None: ...

    @beartype
    def find_frame_view(self, batch_id: str, index: int) -> FrameView | None: ...

    @beartype
    def list_frame_views(self) -> tuple[FrameView, ...]: ...


@beartype
@dataclass(frozen=True, slots=True)
class ReviewLabels:
    machine_name: str | None
    location_name: str | None
    technician_name: str | None


@runtime_checkable
class ReviewLabelLookup(Protocol):
    @beartype
    def labels_for(self, machine_id: str, technician_id: str) -> ReviewLabels: ...


@beartype
@dataclass(frozen=True, slots=True)
class GroupAvatar:
    content: bytes
    content_type: str


@runtime_checkable
class GroupAvatarReader(Protocol):
    @beartype
    def read_avatar(self, group_id: str) -> GroupAvatar | None: ...


@runtime_checkable
class GroupAvatarWriter(Protocol):
    @beartype
    def write_avatar(self, group_id: str, content: bytes, content_type: str) -> None: ...


@runtime_checkable
class LearnedReferenceWriter(Protocol):
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
    ) -> None: ...


class LearnedAppendSkipped(Exception):
    """Writer skipped append; ``reason`` is ``skip_cap`` or ``skip_dup``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
