from __future__ import annotations

import mongomock

from src.application.visit_photo_review.profile import (
    VisitPhotoProfile,
    VisitPhotoProfileMember,
    migrate_checklist_items_to_groups,
)
from src.infrastructure.mongodb.visit_photo_profiles import MongoVisitPhotoProfileStore


def test_mongo_visit_photo_profile_roundtrip() -> None:
    collection = mongomock.MongoClient().db.visit_photo_profiles
    store = MongoVisitPhotoProfileStore(collection)
    profile = VisitPhotoProfile(
        profile_id="p1",
        name="Coffee floor",
        members=frozenset(
            {VisitPhotoProfileMember(model_id="saeco", stand_type_id=None)},
        ),
        groups=migrate_checklist_items_to_groups(("1. A", "2. B")),
        pack_key="coffee_default",
        technician_reference_keys=(),
    )
    store.upsert(profile)
    found = store.get("p1")
    assert found is not None
    assert found.name == "Coffee floor"
    assert found.min_photo_count == 2
    assert found.max_photo_count == 2
    assert found.pack_key == "coffee_default"
    assert found.checklist_items == ("1. A", "2. B")
    listed = store.list_all()
    assert len(listed) == 1
    assert listed[0].profile_id == "p1"


def test_mongo_legacy_checklist_items_migrates_on_read() -> None:
    collection = mongomock.MongoClient().db.visit_photo_profiles
    store = MongoVisitPhotoProfileStore(collection)
    collection.replace_one(
        {"_id": "legacy"},
        {
            "_id": "legacy",
            "name": "Old",
            "members": [{"model_id": "saeco", "stand_type_id": None}],
            "checklist_items": ["Only cue"],
            "pack_key": "pack",
            "technician_reference_keys": [],
        },
        upsert=True,
    )
    found = store.get("legacy")
    assert found is not None
    assert found.checklist_items == ("Only cue",)
    assert len(found.groups) >= 4
