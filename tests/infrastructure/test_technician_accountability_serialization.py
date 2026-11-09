from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.ids import BatchId, EventId, FindingId, MachineId, TechnicianId
from src.domain.technician_accountability.events import PhotoDuplicateSuspected
from src.infrastructure.mongodb.technician_accountability_serialization import (
    accountability_event_from_document,
    accountability_event_to_document,
)


def test_technician_accountability_serialization_round_trip() -> None:
    event = PhotoDuplicateSuspected(
        event_id=EventId("evt-1"),
        finding_id=FindingId("find-1"),
        technician_id=TechnicianId("tech-1"),
        new_batch_id=BatchId("batch-new"),
        matched_batch_id=BatchId("batch-old"),
        new_machine_id=MachineId("101"),
        matched_machine_id=MachineId("102"),
        content_hash="abc",
        photo_index=0,
        detected_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    )
    doc = accountability_event_to_document(event, aggregate_version=1)
    restored = accountability_event_from_document(doc)
    assert isinstance(restored, PhotoDuplicateSuspected)
    assert restored.event_id == event.event_id
    assert restored.finding_id == event.finding_id
    assert restored.content_hash == "abc"


def test_accountability_event_from_document_invalid_shape_raises() -> None:
    with pytest.raises(ValueError, match="invalid shape"):
        accountability_event_from_document(
            {
                "event_id": "evt-1",
                "event_type": "PhotoDuplicateSuspected",
                "occurred_at": datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
            }
        )
