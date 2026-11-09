from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.ids import BatchId, EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
)
from src.domain.models import RevisionSource
from src.infrastructure.mongodb.serialization import (
    document_from_event,
    event_from_bson,
    event_to_document,
)


def test_revision_completed_roundtrip() -> None:
    event = RevisionCompleted(
        event_id=EventId("evt-1"),
        revision_id=RevisionId("rev-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        completed_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token="token-1",
    )

    document = event_to_document(event, aggregate_version=1)
    restored = event_from_bson(document_from_event(event, aggregate_version=1))

    assert restored == event
    assert document.aggregate_id == "vm-01"
    assert document.aggregate_version == 1


def test_revision_completed_roundtrip_with_responsibility_expires_at() -> None:
    expires_at = datetime(2026, 5, 25, 23, 59, 59, 999999, tzinfo=UTC)
    event = RevisionCompleted(
        event_id=EventId("evt-1"),
        revision_id=RevisionId("rev-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        completed_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token="token-1",
        responsibility_expires_at=expires_at,
    )
    restored = event_from_bson(document_from_event(event, aggregate_version=1))
    assert restored == event
    assert restored.responsibility_expires_at == expires_at


def test_loading_submitted_roundtrip() -> None:
    event = LoadingSubmitted(
        event_id=EventId("evt-2"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        submitted_at=datetime(2026, 5, 16, 10, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 16, 10, 0, tzinfo=UTC),
        form_id="form-2",
        form_token="token-2",
    )

    restored = event_from_bson(document_from_event(event, aggregate_version=2))

    assert restored == event


def test_event_from_bson_rejects_pre_loading_type_after_r2() -> None:
    document = {
        "event_id": "evt-pre-1",
        "event_type": "PreLoadingSubmitted",
        "aggregate_id": "vm-01",
        "aggregate_type": "MachineOperations",
        "aggregate_version": 4,
        "occurred_at": datetime(2026, 5, 16, 9, 30, tzinfo=UTC),
        "payload": {
            "technician_id": "tech-a",
            "machine_id": "vm-01",
            "submitted_at": datetime(2026, 5, 16, 9, 30, tzinfo=UTC),
            "form_id": "form-pre",
            "form_token": "token-pre",
        },
        "metadata": {},
    }
    with pytest.raises(ValueError, match="PreLoadingSubmitted|Unsupported|Unknown"):
        event_from_bson(document)


def test_maintenance_completed_roundtrip() -> None:
    event = MaintenanceCompleted(
        event_id=EventId("evt-3"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        completed_at=datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
    )

    restored = event_from_bson(document_from_event(event, aggregate_version=3))

    assert restored == event


def test_photos_submitted_roundtrip() -> None:
    event = PhotosSubmitted(
        event_id=EventId("evt-photos-1"),
        batch_id=BatchId("batch-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        photo_count=2,
        submitted_at=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
    )

    restored = event_from_bson(document_from_event(event, aggregate_version=5))

    assert restored == event


def test_event_from_bson_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unsupported stored event_type"):
        event_from_bson(
            {
                "event_id": "evt-x",
                "event_type": "Unknown",
                "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
                "payload": {},
            },
        )
