from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.config.mongodb import MongoSettings
from src.domain.ids import BatchId, FindingId, TechnicianId
from src.domain.photo_integrity import PhotoIntegrityFinding, PhotoIntegrityStatus
from src.infrastructure.mongodb.connection import resolve_collection

_VALID_PHOTO_INTEGRITY_STATUSES = frozenset(
    {"pending_review", "confirmed", "false_positive"},
)


@runtime_checkable
class PhotoIntegrityFindingsCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> object: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoPhotoIntegrityFindingStore:
    _collection: PhotoIntegrityFindingsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: PhotoIntegrityFindingsCollection,
    ) -> MongoPhotoIntegrityFindingStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoPhotoIntegrityFindingStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.photo_integrity_findings_collection,
            owner="MongoPhotoIntegrityFindingStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index("finding_id", unique=True, name="finding_id_unique")
        self._collection.create_index(
            [("new_batch_id", 1), ("photo_index", 1), ("content_hash", 1)],
            unique=True,
            name="pending_finding_unique",
        )

    @beartype
    def get_by_finding_id(self, finding_id: str) -> PhotoIntegrityFinding | None:
        document = self._collection.find_one({"finding_id": finding_id})
        if document is None:
            return None
        return _document_to_finding(document)

    @beartype
    def find_pending(
        self,
        *,
        batch_id: BatchId,
        photo_index: int,
        content_hash: str,
    ) -> PhotoIntegrityFinding | None:
        document = self._collection.find_one(
            {
                "new_batch_id": batch_id.value,
                "photo_index": photo_index,
                "content_hash": content_hash,
                "status": "pending_review",
            },
        )
        if document is None:
            return None
        return _document_to_finding(document)

    @beartype
    def save(self, finding: PhotoIntegrityFinding) -> None:
        self._collection.replace_one(
            {"finding_id": finding.finding_id.value},
            _finding_to_document(finding),
            upsert=True,
        )

    @beartype
    def mark_alert_sent(self, finding_id: FindingId, sent_at: datetime) -> None:
        finding = self.get_by_finding_id(finding_id.value)
        if finding is None:
            return
        self.save(replace(finding, alert_sent_at=sent_at))


@beartype
def _finding_to_document(finding: PhotoIntegrityFinding) -> dict[str, Any]:
    document: dict[str, Any] = {
        "finding_id": finding.finding_id.value,
        "status": finding.status,
        "new_batch_id": finding.new_batch_id.value,
        "matched_batch_id": finding.matched_batch_id.value,
        "technician_id": finding.technician_id.value,
        "content_hash": finding.content_hash,
        "photo_index": finding.photo_index,
        "detected_at": finding.detected_at,
    }
    if finding.reviewed_at is not None:
        document["reviewed_at"] = finding.reviewed_at
    if finding.alert_sent_at is not None:
        document["alert_sent_at"] = finding.alert_sent_at
    return document


@beartype
def _document_to_finding(document: dict[str, Any]) -> PhotoIntegrityFinding:
    finding_id = document.get("finding_id")
    status = document.get("status")
    new_batch_id = document.get("new_batch_id")
    matched_batch_id = document.get("matched_batch_id")
    technician_id = document.get("technician_id")
    content_hash = document.get("content_hash")
    photo_index = document.get("photo_index")
    detected_at = document.get("detected_at")
    reviewed_at = document.get("reviewed_at")
    alert_sent_at = document.get("alert_sent_at")
    if not isinstance(finding_id, str):
        raise ValueError("Photo integrity finding document has invalid shape")
    if status not in _VALID_PHOTO_INTEGRITY_STATUSES:
        raise ValueError(f"Invalid photo integrity status: {status!r}")
    if (
        not isinstance(new_batch_id, str)
        or not isinstance(matched_batch_id, str)
        or not isinstance(technician_id, str)
        or not isinstance(content_hash, str)
        or not isinstance(photo_index, int)
        or not isinstance(detected_at, datetime)
    ):
        raise ValueError("Photo integrity finding document has invalid shape")
    resolved_status = cast(PhotoIntegrityStatus, status)
    return PhotoIntegrityFinding(
        finding_id=FindingId(finding_id),
        status=resolved_status,
        new_batch_id=BatchId(new_batch_id),
        matched_batch_id=BatchId(matched_batch_id),
        technician_id=TechnicianId(technician_id),
        content_hash=content_hash,
        photo_index=photo_index,
        detected_at=detected_at,
        reviewed_at=reviewed_at if isinstance(reviewed_at, datetime) else None,
        alert_sent_at=alert_sent_at if isinstance(alert_sent_at, datetime) else None,
    )
