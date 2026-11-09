from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    TRASH_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
    is_photo_only_group,
    service_group_title,
)

DEFAULT_VISIT_PHOTO_PROFILE_ID = "default"

SERVICE_PROFILE_GROUP_IDS = frozenset(
    {TRASH_GROUP_ID, POOR_QUALITY_GROUP_ID, UNRECOGNIZED_GROUP_ID}
)

_SERVICE_SEED_ORDER = (
    (TRASH_GROUP_ID, True),
    (POOR_QUALITY_GROUP_ID, True),
    (UNRECOGNIZED_GROUP_ID, False),
)


def _validated_pack_key(pack_key: str) -> str:
    key = pack_key.strip()
    if not key:
        raise ProfileCommandRejected("pack_key_invalid")
    parts = Path(key).parts
    if len(parts) != 1 or parts[0] in {".", ".."} or Path(key).is_absolute():
        raise ProfileCommandRejected("pack_key_invalid")
    return key


@beartype
@dataclass(frozen=True, slots=True)
class VisitPhotoProfileMember:
    model_id: str
    stand_type_id: str | None


@beartype
@dataclass(frozen=True, slots=True)
class ProfileGroupDefect:
    code: str
    label: str


@beartype
@dataclass(frozen=True, slots=True)
class VisitPhotoProfileGroup:
    group_id: str
    title: str
    required: bool
    defects: tuple[ProfileGroupDefect, ...]
    photo_only: bool = False


@beartype
def is_service_profile_group(group_id: str) -> bool:
    return group_id in SERVICE_PROFILE_GROUP_IDS


@beartype
def content_checklist_items(groups: tuple[VisitPhotoProfileGroup, ...]) -> tuple[str, ...]:
    return tuple(group.title for group in groups if not is_service_profile_group(group.group_id))


@beartype
def seed_service_groups() -> tuple[VisitPhotoProfileGroup, ...]:
    rows: list[VisitPhotoProfileGroup] = []
    for group_id, photo_only in _SERVICE_SEED_ORDER:
        title = service_group_title(group_id)
        if title is None:
            title = "Не удалось определить" if group_id == UNRECOGNIZED_GROUP_ID else group_id
        rows.append(
            VisitPhotoProfileGroup(
                group_id=group_id,
                title=title,
                required=False,
                defects=(),
                photo_only=photo_only or is_photo_only_group(group_id),
            )
        )
    return tuple(rows)


@beartype
def migrate_checklist_items_to_groups(
    checklist_items: tuple[str, ...],
) -> tuple[VisitPhotoProfileGroup, ...]:
    content: list[VisitPhotoProfileGroup] = []
    for index, raw in enumerate(checklist_items, start=1):
        title = raw.strip()
        if not title:
            continue
        content.append(
            VisitPhotoProfileGroup(
                group_id=f"cue-{index}",
                title=title,
                required=True,
                defects=(),
                photo_only=False,
            )
        )
    return seed_service_groups() + tuple(content)


@beartype
def remove_profile_group(
    groups: tuple[VisitPhotoProfileGroup, ...],
    group_id: str,
) -> tuple[VisitPhotoProfileGroup, ...]:
    return tuple(group for group in groups if group.group_id != group_id)


def _ensure_service_groups(
    groups: tuple[VisitPhotoProfileGroup, ...],
) -> tuple[VisitPhotoProfileGroup, ...]:
    by_id = {group.group_id: group for group in groups}
    ordered: list[VisitPhotoProfileGroup] = []
    for seeded in seed_service_groups():
        ordered.append(by_id.pop(seeded.group_id, seeded))
    for group in groups:
        if group.group_id in SERVICE_PROFILE_GROUP_IDS:
            continue
        ordered.append(group)
    return tuple(ordered)


def _validate_groups(groups: tuple[VisitPhotoProfileGroup, ...]) -> None:
    seen: set[str] = set()
    for group in groups:
        if group.group_id in seen:
            raise ProfileCommandRejected("duplicate_group_id")
        seen.add(group.group_id)
        if not group.group_id.strip() or not group.title.strip():
            raise ProfileCommandRejected("checklist_empty")
    if not content_checklist_items(groups):
        raise ProfileCommandRejected("checklist_empty")


@beartype
@dataclass(frozen=True, slots=True)
class VisitPhotoProfile:
    profile_id: str
    name: str
    members: frozenset[VisitPhotoProfileMember]
    groups: tuple[VisitPhotoProfileGroup, ...]
    pack_key: str
    technician_reference_keys: tuple[str, ...] = ()

    @property
    def checklist_items(self) -> tuple[str, ...]:
        return content_checklist_items(self.groups)

    @property
    def photo_count(self) -> int:
        return len(self.checklist_items)

    @property
    def min_photo_count(self) -> int:
        return self.photo_count

    @property
    def max_photo_count(self) -> int:
        return self.photo_count


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeModelInfo:
    model_id: str
    floor_standing: bool


@beartype
@dataclass(frozen=True, slots=True)
class MachineEquipmentFacts:
    machine_id: str
    kind: str
    model_id: str | None
    stand_type_id: str | None


class ProfileCommandRejected(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class ProfileTechRefStorageError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


@runtime_checkable
class VisitPhotoProfileStore(Protocol):
    @beartype
    def get(self, profile_id: str) -> VisitPhotoProfile | None: ...

    @beartype
    def upsert(self, profile: VisitPhotoProfile) -> None: ...

    @beartype
    def list_all(self) -> tuple[VisitPhotoProfile, ...]: ...

    @beartype
    def delete(self, profile_id: str) -> None: ...


@runtime_checkable
class CoffeeEquipmentCatalogLookup(Protocol):
    @beartype
    def model_of(self, model_id: str) -> CoffeeModelInfo | None: ...

    @beartype
    def stand_type_exists(self, stand_type_id: str) -> bool: ...


@runtime_checkable
class MachineEquipmentLookup(Protocol):
    @beartype
    def equipment_of(self, machine_id: str) -> MachineEquipmentFacts | None: ...


@runtime_checkable
class VisitPhotoProfileTechRefStorage(Protocol):
    @beartype
    def list_keys(self, profile_id: str) -> tuple[str, ...]: ...

    @beartype
    def save(self, profile_id: str, *, filename: str, payload: bytes) -> str: ...

    @beartype
    def delete(self, profile_id: str, key: str) -> None: ...


@runtime_checkable
class ProfileGroupReferenceLayout(Protocol):
    @beartype
    def ensure_dirs(self, pack_key: str, group_ids: tuple[str, ...]) -> None: ...


@beartype
@dataclass(slots=True)
class InMemoryVisitPhotoProfileStore:
    _by_id: dict[str, VisitPhotoProfile] = field(default_factory=dict)

    def get(self, profile_id: str) -> VisitPhotoProfile | None:
        return self._by_id.get(profile_id)

    def upsert(self, profile: VisitPhotoProfile) -> None:
        self._by_id[profile.profile_id] = profile

    def list_all(self) -> tuple[VisitPhotoProfile, ...]:
        return tuple(self._by_id.values())

    def delete(self, profile_id: str) -> None:
        self._by_id.pop(profile_id, None)


def _validate_members(
    members: frozenset[VisitPhotoProfileMember],
    catalog: CoffeeEquipmentCatalogLookup,
) -> None:
    if not members:
        raise ProfileCommandRejected("members_empty")
    for member in members:
        model = catalog.model_of(member.model_id)
        if model is None:
            raise ProfileCommandRejected("unknown_catalog_entry")
        if model.floor_standing:
            if member.stand_type_id is not None:
                raise ProfileCommandRejected("stand_not_allowed_for_floor_model")
        else:
            if member.stand_type_id is None:
                raise ProfileCommandRejected("stand_required")
            if not catalog.stand_type_exists(member.stand_type_id):
                raise ProfileCommandRejected("unknown_catalog_entry")


def _assert_no_overlap(
    store: VisitPhotoProfileStore,
    *,
    profile_id: str,
    members: frozenset[VisitPhotoProfileMember],
) -> None:
    for existing in store.list_all():
        if existing.profile_id == profile_id:
            continue
        if existing.members & members:
            raise ProfileCommandRejected("profile_member_overlap")


@beartype
@dataclass(frozen=True, slots=True)
class SaveVisitPhotoProfile:
    store: VisitPhotoProfileStore
    catalog: CoffeeEquipmentCatalogLookup
    reference_layout: ProfileGroupReferenceLayout | None = None

    def __call__(
        self,
        *,
        profile_id: str,
        name: str,
        members: frozenset[VisitPhotoProfileMember],
        pack_key: str,
        groups: tuple[VisitPhotoProfileGroup, ...] | None = None,
        checklist_items: tuple[str, ...] | None = None,
        technician_reference_keys: tuple[str, ...] = (),
    ) -> VisitPhotoProfile:
        trimmed_name = name.strip()
        if not trimmed_name:
            raise ProfileCommandRejected("catalog_name_invalid")
        if groups is None:
            if not checklist_items:
                raise ProfileCommandRejected("checklist_empty")
            if any(not item.strip() for item in checklist_items):
                raise ProfileCommandRejected("checklist_empty")
            resolved_groups = migrate_checklist_items_to_groups(
                tuple(item.strip() for item in checklist_items)
            )
        else:
            resolved_groups = _ensure_service_groups(groups)
            _validate_groups(resolved_groups)
        pack = _validated_pack_key(pack_key)
        _validate_members(members, self.catalog)
        _assert_no_overlap(self.store, profile_id=profile_id, members=members)
        profile = VisitPhotoProfile(
            profile_id=profile_id,
            name=trimmed_name,
            members=members,
            groups=resolved_groups,
            pack_key=pack,
            technician_reference_keys=technician_reference_keys,
        )
        self.store.upsert(profile)
        if self.reference_layout is not None:
            self.reference_layout.ensure_dirs(
                pack,
                tuple(group.group_id for group in resolved_groups),
            )
        return profile


@beartype
@dataclass(frozen=True, slots=True)
class ResolveVisitPhotoProfile:
    store: VisitPhotoProfileStore
    machines: MachineEquipmentLookup

    def __call__(self, machine_id: str) -> VisitPhotoProfile | None:
        facts = self.machines.equipment_of(machine_id)
        if facts is None or facts.kind != "coffee":
            return None
        if not facts.model_id:
            return None
        key = VisitPhotoProfileMember(
            model_id=facts.model_id,
            stand_type_id=facts.stand_type_id,
        )
        for profile in self.store.list_all():
            if key in profile.members:
                return profile
        return None

    def default_profile(self) -> VisitPhotoProfile | None:
        """Cutover migration profile ``default`` when membership miss and not strict."""
        return self.store.get(DEFAULT_VISIT_PHOTO_PROFILE_ID)
