from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from beartype import beartype


class CatalogInvalid(ValueError):
    """Catalog JSON payload is structurally invalid."""


UNRECOGNIZED_GROUP_ID = "unrecognized"
POOR_QUALITY_GROUP_ID = "poor_quality"
TRASH_GROUP_ID = "trash"

PHOTO_ONLY_GROUP_IDS = frozenset({POOR_QUALITY_GROUP_ID, TRASH_GROUP_ID})

_SERVICE_GROUP_TITLES = {
    POOR_QUALITY_GROUP_ID: "Некачественное фото",
    TRASH_GROUP_ID: "Мусор",
}


@beartype
def is_photo_only_group(group_id: str) -> bool:
    return group_id in PHOTO_ONLY_GROUP_IDS


@beartype
def service_group_title(group_id: str) -> str | None:
    return _SERVICE_GROUP_TITLES.get(group_id)


class AssignError(StrEnum):
    BATCH_NOT_ACCEPTED = "batch_not_accepted"
    UNKNOWN_GROUP = "unknown_group"
    INDEX_WITHOUT_FILE = "index_without_file"
    EMPTY_GROUP = "empty_group"
    DUPLICATE_INDEX = "duplicate_index"
    CATALOG_UNAVAILABLE = "catalog_unavailable"


class MissingGroupError(StrEnum):
    BATCH_NOT_ACCEPTED = "batch_not_accepted"
    GROUP_NOT_REQUIRED = "group_not_required"
    HAS_ASSIGNMENT = "has_assignment"
    HAS_HUMAN_RECORD = "has_human_record"
    CATALOG_UNAVAILABLE = "catalog_unavailable"


class SaveError(StrEnum):
    NO_LIVE_ASSIGNMENT = "no_live_assignment"
    NO_MARKS = "no_marks"
    UNKNOWN_DEFECT = "unknown_defect"
    CATALOG_UNAVAILABLE = "catalog_unavailable"
    INVALID_FRAME_INDEX = "invalid_frame_index"


@beartype
@dataclass(frozen=True, slots=True)
class GroupAssignment:
    batch_id: str
    group_id: str
    indexes: tuple[int, ...]
    machine_id: str
    technician_id: str
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class DefectMark:
    code: str
    label: str


@beartype
@dataclass(frozen=True, slots=True)
class ReviewRecord:
    batch_id: str
    group_id: str
    record_kind: Literal["human", "missing"]
    indexes: tuple[int, ...]
    defects: tuple[DefectMark, ...]
    system_error: bool
    comment: str
    creator_kind: Literal["human", "system"]
    actor_user_id: str | None
    saved_at: datetime
    group_title: str
    machine_id: str
    technician_id: str
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class FrameView:
    batch_id: str
    index: int
    actor_user_id: str
    viewed_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class Result[T, E]:
    _value: T | None = None
    _error: E | None = None
    _is_ok: bool = False

    @classmethod
    def ok(cls, value: T) -> Result[T, E]:
        return cls(_value=value, _error=None, _is_ok=True)

    @classmethod
    def err(cls, error: E) -> Result[T, E]:
        return cls(_value=None, _error=error, _is_ok=False)

    def is_ok(self) -> bool:
        return self._is_ok

    def is_err(self) -> bool:
        return not self._is_ok

    @property
    def value(self) -> T:
        if not self._is_ok:
            msg = "Result is error"
            raise ValueError(msg)
        return self._value  # type: ignore[return-value]

    @property
    def error(self) -> E:
        if self._is_ok:
            msg = "Result is ok"
            raise ValueError(msg)
        return self._error  # type: ignore[return-value]


@beartype
@dataclass(frozen=True, slots=True)
class DefectButton:
    code: str
    label: str


@beartype
@dataclass(frozen=True, slots=True)
class CatalogGroup:
    group_id: str
    title: str
    required: bool
    defects: tuple[DefectButton, ...]


@beartype
@dataclass(frozen=True, slots=True)
class ReviewCatalog:
    groups: tuple[CatalogGroup, ...]

    def group(self, group_id: str) -> CatalogGroup | None:
        for item in self.groups:
            if item.group_id == group_id:
                return item
        return None

    def order_index(self, group_id: str) -> int:
        for index, item in enumerate(self.groups):
            if item.group_id == group_id:
                return index
        raise KeyError(group_id)


@beartype
def parse_review_catalog(payload: object) -> ReviewCatalog:
    if not isinstance(payload, dict):
        raise CatalogInvalid("catalog payload must be an object")
    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        raise CatalogInvalid("groups must be a list")
    if not raw_groups:
        raise CatalogInvalid("groups must not be empty")

    seen_group_ids: set[str] = set()
    groups: list[CatalogGroup] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            raise CatalogInvalid("group must be an object")
        group_id = _require_nonempty_str(raw_group.get("group_id"), "group_id")
        title = _require_nonempty_str(raw_group.get("title"), "title")
        if group_id in seen_group_ids:
            raise CatalogInvalid(f"duplicate group_id: {group_id}")
        seen_group_ids.add(group_id)
        required = bool(raw_group.get("required", False))
        raw_defects = raw_group.get("defects", [])
        if raw_defects is None:
            raw_defects = []
        if not isinstance(raw_defects, list):
            raise CatalogInvalid("defects must be a list")
        seen_codes: set[str] = set()
        defects: list[DefectButton] = []
        for raw_defect in raw_defects:
            if not isinstance(raw_defect, dict):
                raise CatalogInvalid("defect must be an object")
            code = _require_nonempty_str(raw_defect.get("code"), "code")
            label = _require_nonempty_str(raw_defect.get("label"), "label")
            if code in seen_codes:
                raise CatalogInvalid(f"duplicate defect code: {code}")
            seen_codes.add(code)
            defects.append(DefectButton(code=code, label=label))
        groups.append(
            CatalogGroup(
                group_id=group_id,
                title=title,
                required=required,
                defects=tuple(defects),
            )
        )
    return ReviewCatalog(groups=tuple(groups))


@beartype
def require_reserved_catalog_groups(catalog: ReviewCatalog) -> None:
    for group_id in (UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID):
        group = catalog.group(group_id)
        if group is None:
            raise CatalogInvalid(f"catalog missing reserved group: {group_id}")
        if group.required:
            raise CatalogInvalid(f"reserved group must not be required: {group_id}")


@beartype
def review_catalog_to_payload(catalog: ReviewCatalog) -> dict[str, object]:
    return {
        "groups": [
            {
                "group_id": group.group_id,
                "title": group.title,
                "required": group.required,
                "defects": [
                    {"code": defect.code, "label": defect.label} for defect in group.defects
                ],
            }
            for group in catalog.groups
        ],
    }


def _require_nonempty_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise CatalogInvalid(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise CatalogInvalid(f"{field_name} must be non-empty")
    return stripped
