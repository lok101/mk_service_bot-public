from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.visit_photo_review.profile import (
    ProfileGroupDefect,
    VisitPhotoProfile,
    VisitPhotoProfileGroup,
    VisitPhotoProfileMember,
    migrate_checklist_items_to_groups,
)
from src.config.mongodb import MongoSettings
from src.config.visit_photo_review import VisitPhotoReviewSettings
from src.infrastructure.mongodb.connection import (
    MongoCollectionSource,
    resolve_collection,
)


def _parse_member(raw: object) -> VisitPhotoProfileMember:
    if not isinstance(raw, dict):
        raise ValueError("profile member must be an object")
    model_id = raw.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("member.model_id must be non-empty str")
    stand = raw.get("stand_type_id")
    if stand is not None and not isinstance(stand, str):
        raise ValueError("member.stand_type_id must be str or null")
    return VisitPhotoProfileMember(model_id=model_id, stand_type_id=stand)


def _parse_profile(document: dict[str, Any]) -> VisitPhotoProfile:
    profile_id = document.get("_id")
    if not isinstance(profile_id, str):
        raise ValueError("profile_id must be str")
    name = document.get("name")
    if not isinstance(name, str):
        raise ValueError("name must be str")
    pack_key = document.get("pack_key")
    if not isinstance(pack_key, str):
        raise ValueError("pack_key must be str")
    raw_members = document.get("members")
    if not isinstance(raw_members, list):
        raise ValueError("members must be a list")
    members = frozenset(_parse_member(item) for item in raw_members)
    raw_refs = document.get("technician_reference_keys", [])
    if not isinstance(raw_refs, list) or not all(isinstance(item, str) for item in raw_refs):
        raise ValueError("technician_reference_keys must be list[str]")
    groups = _parse_groups(document)
    return VisitPhotoProfile(
        profile_id=profile_id,
        name=name,
        members=members,
        groups=groups,
        pack_key=pack_key,
        technician_reference_keys=tuple(raw_refs),
    )


def _parse_defect(raw: object) -> ProfileGroupDefect:
    if not isinstance(raw, dict):
        raise ValueError("defect must be an object")
    code = raw.get("code")
    label = raw.get("label")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("defect.code must be non-empty str")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("defect.label must be non-empty str")
    return ProfileGroupDefect(code=code.strip(), label=label.strip())


def _parse_group(raw: object) -> VisitPhotoProfileGroup:
    if not isinstance(raw, dict):
        raise ValueError("group must be an object")
    group_id = raw.get("group_id")
    title = raw.get("title")
    required = raw.get("required", False)
    photo_only = raw.get("photo_only", False)
    raw_defects = raw.get("defects", [])
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("group.group_id must be non-empty str")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("group.title must be non-empty str")
    if not isinstance(required, bool):
        raise ValueError("group.required must be bool")
    if not isinstance(photo_only, bool):
        raise ValueError("group.photo_only must be bool")
    if not isinstance(raw_defects, list):
        raise ValueError("group.defects must be a list")
    return VisitPhotoProfileGroup(
        group_id=group_id.strip(),
        title=title.strip(),
        required=required,
        defects=tuple(_parse_defect(item) for item in raw_defects),
        photo_only=photo_only,
    )


def _parse_groups(document: dict[str, Any]) -> tuple[VisitPhotoProfileGroup, ...]:
    raw_groups = document.get("groups")
    if isinstance(raw_groups, list):
        return tuple(_parse_group(item) for item in raw_groups)
    raw_checklist = document.get("checklist_items")
    if not isinstance(raw_checklist, list) or not all(
        isinstance(item, str) for item in raw_checklist
    ):
        raise ValueError("groups must be a list or legacy checklist_items list[str]")
    return migrate_checklist_items_to_groups(tuple(raw_checklist))


@beartype
class MongoVisitPhotoProfileStore:
    def __init__(self, collection: MongoCollectionSource) -> None:
        self._collection = collection

    def get(self, profile_id: str) -> VisitPhotoProfile | None:
        document = self._collection.find_one({"_id": profile_id})
        if document is None:
            return None
        if not isinstance(document, dict):
            raise ValueError("profile document must be an object")
        return _parse_profile(document)

    def upsert(self, profile: VisitPhotoProfile) -> None:
        payload = {
            "_id": profile.profile_id,
            "name": profile.name,
            "members": [
                {"model_id": m.model_id, "stand_type_id": m.stand_type_id}
                for m in sorted(
                    profile.members,
                    key=lambda item: (item.model_id, item.stand_type_id or ""),
                )
            ],
            "groups": [
                {
                    "group_id": group.group_id,
                    "title": group.title,
                    "required": group.required,
                    "photo_only": group.photo_only,
                    "defects": [
                        {"code": defect.code, "label": defect.label} for defect in group.defects
                    ],
                }
                for group in profile.groups
            ],
            "checklist_items": list(profile.checklist_items),
            "pack_key": profile.pack_key,
            "technician_reference_keys": list(profile.technician_reference_keys),
        }
        self._collection.replace_one({"_id": profile.profile_id}, payload, upsert=True)

    def list_all(self) -> tuple[VisitPhotoProfile, ...]:
        rows: list[VisitPhotoProfile] = []
        for document in self._collection.find({}):
            if not isinstance(document, dict):
                raise ValueError("profile document must be an object")
            rows.append(_parse_profile(document))
        return tuple(rows)

    def delete(self, profile_id: str) -> None:
        self._collection.delete_one({"_id": profile_id})


@beartype
def build_mongo_visit_photo_profile_store(
    mongo: MongoSettings,
    review: VisitPhotoReviewSettings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MongoVisitPhotoProfileStore:
    collection = resolve_collection(
        mongo,
        client=client,
        collection_name=review.profiles_collection,
        owner="MongoVisitPhotoProfileStore",
    )
    return MongoVisitPhotoProfileStore(collection)
