from __future__ import annotations

from datetime import UTC, datetime

import mongomock
import pytest

from src.domain.ids import BatchId, FindingId, TechnicianId
from src.domain.photo_integrity import PhotoIntegrityFinding
from src.infrastructure.mongodb.photo_integrity_findings import MongoPhotoIntegrityFindingStore

_DETECTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
_SENT_AT = datetime(2026, 5, 20, 12, 5, tzinfo=UTC)


def _sample_finding(*, alert_sent_at: datetime | None = None) -> PhotoIntegrityFinding:
    return PhotoIntegrityFinding(
        finding_id=FindingId("542b3aa24661579490b577dd5aad9e6f"),
        status="pending_review",
        new_batch_id=BatchId("batch-new"),
        matched_batch_id=BatchId("batch-old"),
        technician_id=TechnicianId("tech-1"),
        content_hash="a" * 64,
        photo_index=0,
        detected_at=_DETECTED_AT,
        alert_sent_at=alert_sent_at,
    )


def test_mongodb_photo_integrity_findings_mark_alert_sent_updates_existing_row() -> None:
    collection = mongomock.MongoClient().db.photo_integrity_findings
    store = MongoPhotoIntegrityFindingStore.from_collection(collection)

    finding = _sample_finding()
    store.save(finding)
    store.mark_alert_sent(finding.finding_id, _SENT_AT)

    loaded = store.get_by_finding_id(finding.finding_id.value)
    assert loaded is not None
    assert loaded.alert_sent_at is not None
    assert loaded.alert_sent_at.replace(tzinfo=UTC) == _SENT_AT


def test_mongodb_photo_integrity_findings_rejects_invalid_status() -> None:
    collection = mongomock.MongoClient().db.photo_integrity_findings
    collection.insert_one(
        {
            "finding_id": "finding-invalid",
            "status": "corrupted",
            "new_batch_id": "batch-new",
            "matched_batch_id": "batch-old",
            "technician_id": "tech-1",
            "content_hash": "a" * 64,
            "photo_index": 0,
            "detected_at": _DETECTED_AT,
        },
    )
    store = MongoPhotoIntegrityFindingStore.from_collection(collection)

    with pytest.raises(ValueError, match="Invalid photo integrity status: 'corrupted'"):
        store.get_by_finding_id("finding-invalid")


def test_mongodb_photo_integrity_findings_save_is_idempotent() -> None:
    collection = mongomock.MongoClient().db.photo_integrity_findings
    store = MongoPhotoIntegrityFindingStore.from_collection(collection)

    finding = _sample_finding()
    store.save(finding)
    store.save(_sample_finding(alert_sent_at=_SENT_AT))

    loaded = store.get_by_finding_id(finding.finding_id.value)
    assert loaded is not None
    assert loaded.alert_sent_at is not None
    assert loaded.alert_sent_at.replace(tzinfo=UTC) == _SENT_AT
