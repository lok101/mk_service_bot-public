from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class GroupingStoredFile:
    index: int
    storage_key: str
    content_type: str
    content_hash: str


@beartype
@dataclass(frozen=True, slots=True)
class GroupingBatchView:
    batch_id: str
    machine_id: str
    status: str
    files: tuple[GroupingStoredFile, ...]


@beartype
@dataclass(frozen=True, slots=True)
class GroupingGroup:
    group_id: str
    indexes: tuple[int, ...]


@beartype
@dataclass(frozen=True, slots=True)
class GroupingSuccess:
    groups: tuple[GroupingGroup, ...]


@beartype
@dataclass(frozen=True, slots=True)
class GroupingTemporaryFailure:
    reason_code: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class GroupingPermanentFailure:
    pass


@runtime_checkable
class GroupingBatchReader(Protocol):
    @beartype
    def get(self, batch_id: str) -> GroupingBatchView | None: ...


@runtime_checkable
class MachineReviewParticipation(Protocol):
    @beartype
    def include(self, machine_id: str) -> bool: ...


@runtime_checkable
class GroupClassifier(Protocol):
    @beartype
    def classify(
        self,
        batch_id: str,
        files: tuple[GroupingStoredFile, ...],
    ) -> GroupingSuccess | GroupingTemporaryFailure | GroupingPermanentFailure: ...
