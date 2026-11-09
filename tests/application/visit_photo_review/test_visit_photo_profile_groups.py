from __future__ import annotations

import pytest
from tests.application.visit_photo_review.test_visit_photo_profile import (
    _FakeCatalog,
    _save,
)

from src.application.visit_photo_review.profile import (
    InMemoryVisitPhotoProfileStore,
    ProfileCommandRejected,
    SaveVisitPhotoProfile,
    VisitPhotoProfileGroup,
    VisitPhotoProfileMember,
    content_checklist_items,
    migrate_checklist_items_to_groups,
    remove_profile_group,
    seed_service_groups,
)
from src.domain.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    TRASH_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
)


def test_content_groups_derive_checklist_min_max() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    groups = seed_service_groups() + (
        VisitPhotoProfileGroup(
            group_id="before",
            title="До обслуживания",
            required=True,
            defects=(),
            photo_only=False,
        ),
        VisitPhotoProfileGroup(
            group_id="after",
            title="После",
            required=True,
            defects=(),
            photo_only=False,
        ),
    )
    cmd = SaveVisitPhotoProfile(store=store, catalog=catalog)
    profile = cmd(
        profile_id="p1",
        name="Profile",
        members=frozenset({VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")}),
        groups=groups,
        pack_key="pack-a",
    )
    assert profile.checklist_items == ("До обслуживания", "После")
    assert profile.photo_count == 2
    assert profile.min_photo_count == 2
    assert profile.max_photo_count == 2


def test_migrate_checklist_items_to_content_groups() -> None:
    migrated = migrate_checklist_items_to_groups(("1. A", "2. B"))
    assert content_checklist_items(migrated) == ("1. A", "2. B")
    ids = {group.group_id for group in migrated}
    assert TRASH_GROUP_ID in ids
    assert POOR_QUALITY_GROUP_ID in ids
    assert UNRECOGNIZED_GROUP_ID in ids


def test_reject_empty_content_groups() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    cmd = SaveVisitPhotoProfile(store=store, catalog=catalog)
    with pytest.raises(ProfileCommandRejected) as err:
        cmd(
            profile_id="p1",
            name="Profile",
            members=frozenset({VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")}),
            groups=seed_service_groups(),
            pack_key="pack-a",
        )
    assert err.value.code == "checklist_empty"


def test_reject_duplicate_group_id() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    dup = VisitPhotoProfileGroup(
        group_id="same",
        title="A",
        required=True,
        defects=(),
        photo_only=False,
    )
    other = VisitPhotoProfileGroup(
        group_id="same",
        title="B",
        required=True,
        defects=(),
        photo_only=False,
    )
    cmd = SaveVisitPhotoProfile(store=store, catalog=catalog)
    with pytest.raises(ProfileCommandRejected) as err:
        cmd(
            profile_id="p1",
            name="Profile",
            members=frozenset({VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")}),
            groups=seed_service_groups() + (dup, other),
            pack_key="pack-a",
        )
    assert err.value.code == "duplicate_group_id"


def test_service_groups_excluded_from_checklist() -> None:
    service = seed_service_groups()
    assert content_checklist_items(service) == ()
    assert {group.group_id for group in service} == {
        TRASH_GROUP_ID,
        POOR_QUALITY_GROUP_ID,
        UNRECOGNIZED_GROUP_ID,
    }


def test_soft_remove_content_group_keeps_others() -> None:
    groups = migrate_checklist_items_to_groups(("Keep", "Drop"))
    drop = next(group for group in groups if group.title == "Drop")
    remaining = remove_profile_group(groups, drop.group_id)
    assert content_checklist_items(remaining) == ("Keep",)
    assert drop.group_id not in {group.group_id for group in remaining}


def test_legacy_checklist_save_seeds_service_groups() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    profile = _save(
        store,
        catalog,
        profile_id="legacy",
        name="Legacy",
        members=frozenset({VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")}),
        checklist=("Cue one", "Cue two"),
    )
    ids = {group.group_id for group in profile.groups}
    assert TRASH_GROUP_ID in ids
    assert profile.checklist_items == ("Cue one", "Cue two")
