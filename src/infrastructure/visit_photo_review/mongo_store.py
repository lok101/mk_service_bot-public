from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING
from pymongo.errors import OperationFailure

from src.domain.visit_photo_review import DefectMark, FrameView, GroupAssignment, ReviewRecord

_INDEX_OPTIONS_CONFLICT_CODES = frozenset({85, 86})


@runtime_checkable
class ReviewStoreCollection(Protocol):
    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...

    def drop_index(self, index_or_name: str | list[tuple[str, int]], **kwargs: Any) -> None: ...

    def index_information(self) -> dict[str, Any]: ...

    def find_one(self, filter: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        **kwargs: Any,
    ) -> Any: ...

    def delete_many(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def delete_one(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def insert_many(self, documents: list[dict[str, Any]], **kwargs: Any) -> Any: ...


@beartype
def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _keys_match(existing_key: object, keys: list[tuple[str, int]]) -> bool:
    if not isinstance(existing_key, list | tuple):
        return False
    normalized: list[tuple[str, int]] = []
    for item in existing_key:
        if not isinstance(item, list | tuple) or len(item) != 2:
            return False
        normalized.append((str(item[0]), int(item[1])))
    return normalized == keys


def _is_index_options_conflict(exc: OperationFailure) -> bool:
    code = getattr(exc, "code", None)
    if code in _INDEX_OPTIONS_CONFLICT_CODES:
        return True
    message = str(exc).lower()
    return "already exists with different options" in message


def _ensure_index(
    collection: ReviewStoreCollection,
    keys: list[tuple[str, int]],
    **kwargs: Any,
) -> None:
    try:
        collection.create_index(keys, **kwargs)
        return
    except OperationFailure as exc:
        if not _is_index_options_conflict(exc):
            raise
    info = collection.index_information()
    for name, meta in info.items():
        if name == "_id_":
            continue
        if _keys_match(meta.get("key"), keys):
            collection.drop_index(name)
    collection.create_index(keys, **kwargs)


def _record_frame_key(record: ReviewRecord) -> int | None:
    if record.record_kind == "missing":
        return None
    if len(record.indexes) == 1:
        return record.indexes[0]
    return None


def _legacy_human_filter(
    batch_id: str, group_id: str, *, frame_index: int | None = None
) -> dict[str, Any]:
    filt: dict[str, Any] = {
        "kind": "record",
        "batch_id": batch_id,
        "group_id": group_id,
        "record_kind": "human",
        "$or": [{"frame_index": None}, {"frame_index": {"$exists": False}}],
    }
    if frame_index is not None:
        filt["indexes"] = frame_index
    return filt


@beartype
class MongoReviewStore:
    def __init__(self, collection: ReviewStoreCollection) -> None:
        self._collection = collection
        # Drop legacy unique that allowed only one record per batch×group.
        for name, meta in self._collection.index_information().items():
            if name == "_id_":
                continue
            if _keys_match(
                meta.get("key"),
                [("kind", ASCENDING), ("batch_id", ASCENDING), ("group_id", ASCENDING)],
            ):
                self._collection.drop_index(name)
        _ensure_index(
            self._collection,
            [("kind", ASCENDING), ("batch_id", ASCENDING), ("group_id", ASCENDING)],
            unique=True,
            partialFilterExpression={"kind": "assignment"},
        )
        _ensure_index(
            self._collection,
            [
                ("kind", ASCENDING),
                ("batch_id", ASCENDING),
                ("group_id", ASCENDING),
                ("frame_index", ASCENDING),
            ],
            unique=True,
            partialFilterExpression={"kind": "record"},
        )
        _ensure_index(
            self._collection,
            [("kind", ASCENDING), ("batch_id", ASCENDING), ("index", ASCENDING)],
            unique=True,
            partialFilterExpression={"kind": "frame_view"},
        )

    @beartype
    def replace_assignments(
        self,
        batch_id: str,
        assignments: tuple[GroupAssignment, ...],
        *,
        clear_missing_group_ids: tuple[str, ...],
    ) -> None:
        # Upsert new set first, then drop stale group_ids — never delete-all before
        # insert (no empty-collection window if a later write fails).
        new_group_ids = {assignment.group_id for assignment in assignments}
        for assignment in assignments:
            self._collection.replace_one(
                {
                    "kind": "assignment",
                    "batch_id": batch_id,
                    "group_id": assignment.group_id,
                },
                _assignment_to_document(assignment),
                upsert=True,
            )
        stale_filter: dict[str, Any] = {"kind": "assignment", "batch_id": batch_id}
        if new_group_ids:
            stale_filter["group_id"] = {"$nin": list(new_group_ids)}
        self._collection.delete_many(stale_filter)
        for group_id in clear_missing_group_ids:
            existing = self._collection.find_one(
                {
                    "kind": "record",
                    "batch_id": batch_id,
                    "group_id": group_id,
                    "record_kind": "missing",
                }
            )
            if existing is not None:
                self._collection.delete_one(
                    {
                        "kind": "record",
                        "batch_id": batch_id,
                        "group_id": group_id,
                        "record_kind": "missing",
                    }
                )

    @beartype
    def find_assignment(self, batch_id: str, group_id: str) -> GroupAssignment | None:
        document = self._collection.find_one(
            {"kind": "assignment", "batch_id": batch_id, "group_id": group_id}
        )
        if document is None:
            return None
        return _document_to_assignment(document)

    @beartype
    def assignments_for_batch(self, batch_id: str) -> tuple[GroupAssignment, ...]:
        return tuple(
            _document_to_assignment(document)
            for document in self._collection.find({"kind": "assignment", "batch_id": batch_id})
        )

    @beartype
    def find_record(self, batch_id: str, group_id: str) -> ReviewRecord | None:
        missing = self._collection.find_one(
            {
                "kind": "record",
                "batch_id": batch_id,
                "group_id": group_id,
                "record_kind": "missing",
            }
        )
        if missing is not None:
            return _document_to_record(missing)
        document = self._collection.find_one(
            {"kind": "record", "batch_id": batch_id, "group_id": group_id, "record_kind": "human"}
        )
        if document is None:
            return None
        return _document_to_record(document)

    @beartype
    def find_frame_record(
        self, batch_id: str, group_id: str, frame_index: int
    ) -> ReviewRecord | None:
        exact = self._collection.find_one(
            {
                "kind": "record",
                "batch_id": batch_id,
                "group_id": group_id,
                "frame_index": frame_index,
                "record_kind": "human",
            }
        )
        if exact is not None:
            return _document_to_record(exact)
        legacy = self._collection.find_one(
            _legacy_human_filter(batch_id, group_id, frame_index=frame_index)
        )
        if legacy is None:
            return None
        return _document_to_record(legacy)

    def _detach_frame_from_legacy(self, batch_id: str, group_id: str, frame_index: int) -> None:
        legacy = self._collection.find_one(
            _legacy_human_filter(batch_id, group_id, frame_index=frame_index)
        )
        if legacy is None:
            return
        remaining = [int(index) for index in legacy["indexes"] if int(index) != frame_index]
        if not remaining:
            self._collection.delete_one({"_id": legacy["_id"]})
            return
        rewritten = dict(legacy)
        rewritten["indexes"] = remaining
        self._collection.replace_one({"_id": legacy["_id"]}, rewritten)

    @beartype
    def records_for_batch(self, batch_id: str) -> tuple[ReviewRecord, ...]:
        return tuple(
            _document_to_record(document)
            for document in self._collection.find({"kind": "record", "batch_id": batch_id})
        )

    @beartype
    def save_record(self, record: ReviewRecord) -> None:
        frame_index = _record_frame_key(record)
        if frame_index is not None:
            self._detach_frame_from_legacy(record.batch_id, record.group_id, frame_index)
        document = _record_to_document(record)
        document["frame_index"] = frame_index
        self._collection.replace_one(
            {
                "kind": "record",
                "batch_id": record.batch_id,
                "group_id": record.group_id,
                "frame_index": frame_index,
            },
            document,
            upsert=True,
        )

    @beartype
    def clear_record(self, batch_id: str, group_id: str, *, frame_index: int | None = None) -> None:
        if frame_index is not None:
            self._collection.delete_one(
                {
                    "kind": "record",
                    "batch_id": batch_id,
                    "group_id": group_id,
                    "frame_index": frame_index,
                }
            )
            self._detach_frame_from_legacy(batch_id, group_id, frame_index)
            return
        self._collection.delete_many({"kind": "record", "batch_id": batch_id, "group_id": group_id})

    @beartype
    def list_assignments(self) -> tuple[GroupAssignment, ...]:
        return tuple(
            _document_to_assignment(document)
            for document in self._collection.find({"kind": "assignment"})
        )

    @beartype
    def list_records(self) -> tuple[ReviewRecord, ...]:
        return tuple(
            _document_to_record(document) for document in self._collection.find({"kind": "record"})
        )

    @beartype
    def save_frame_view(self, view: FrameView) -> None:
        self._collection.replace_one(
            {
                "kind": "frame_view",
                "batch_id": view.batch_id,
                "index": view.index,
            },
            _frame_view_to_document(view),
            upsert=True,
        )

    @beartype
    def find_frame_view(self, batch_id: str, index: int) -> FrameView | None:
        document = self._collection.find_one(
            {"kind": "frame_view", "batch_id": batch_id, "index": index}
        )
        if document is None:
            return None
        return _document_to_frame_view(document)

    @beartype
    def list_frame_views(self) -> tuple[FrameView, ...]:
        return tuple(
            _document_to_frame_view(document)
            for document in self._collection.find({"kind": "frame_view"})
        )


@beartype
def _assignment_to_document(assignment: GroupAssignment) -> dict[str, Any]:
    return {
        "kind": "assignment",
        "batch_id": assignment.batch_id,
        "group_id": assignment.group_id,
        "indexes": list(assignment.indexes),
        "machine_id": assignment.machine_id,
        "technician_id": assignment.technician_id,
        "occurred_at": assignment.occurred_at,
    }


@beartype
def _document_to_assignment(document: dict[str, Any]) -> GroupAssignment:
    return GroupAssignment(
        batch_id=str(document["batch_id"]),
        group_id=str(document["group_id"]),
        indexes=tuple(int(index) for index in document["indexes"]),
        machine_id=str(document["machine_id"]),
        technician_id=str(document["technician_id"]),
        occurred_at=_ensure_aware(document["occurred_at"]),
    )


@beartype
def _record_to_document(record: ReviewRecord) -> dict[str, Any]:
    return {
        "kind": "record",
        "batch_id": record.batch_id,
        "group_id": record.group_id,
        "record_kind": record.record_kind,
        "indexes": list(record.indexes),
        "defects": [{"code": mark.code, "label": mark.label} for mark in record.defects],
        "system_error": record.system_error,
        "comment": record.comment,
        "creator_kind": record.creator_kind,
        "actor_user_id": record.actor_user_id,
        "saved_at": record.saved_at,
        "group_title": record.group_title,
        "machine_id": record.machine_id,
        "technician_id": record.technician_id,
        "occurred_at": record.occurred_at,
    }


@beartype
def _document_to_record(document: dict[str, Any]) -> ReviewRecord:
    raw_defects = document.get("defects") or []
    defects = tuple(
        DefectMark(code=str(item["code"]), label=str(item["label"])) for item in raw_defects
    )
    return ReviewRecord(
        batch_id=str(document["batch_id"]),
        group_id=str(document["group_id"]),
        record_kind=document["record_kind"],
        indexes=tuple(int(index) for index in document["indexes"]),
        defects=defects,
        system_error=bool(document["system_error"]),
        comment=str(document["comment"]),
        creator_kind=document["creator_kind"],
        actor_user_id=(
            None if document.get("actor_user_id") is None else str(document["actor_user_id"])
        ),
        saved_at=_ensure_aware(document["saved_at"]),
        group_title=str(document["group_title"]),
        machine_id=str(document["machine_id"]),
        technician_id=str(document["technician_id"]),
        occurred_at=_ensure_aware(document["occurred_at"]),
    )


@beartype
def _frame_view_to_document(view: FrameView) -> dict[str, Any]:
    return {
        "kind": "frame_view",
        "batch_id": view.batch_id,
        "index": view.index,
        "actor_user_id": view.actor_user_id,
        "viewed_at": view.viewed_at,
    }


@beartype
def _document_to_frame_view(document: dict[str, Any]) -> FrameView:
    return FrameView(
        batch_id=str(document["batch_id"]),
        index=int(document["index"]),
        actor_user_id=str(document["actor_user_id"]),
        viewed_at=_ensure_aware(document["viewed_at"]),
    )
