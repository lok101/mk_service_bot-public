from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import BatchId, FindingId, MachineId, TechnicianId
from src.domain.technician_accountability import (
    RecordPhotoDuplicateSuspected,
    TechnicianAccountability,
)


def test_photo_duplicate_suspected_is_recorded_once() -> None:
    aggregate = TechnicianAccountability.empty(TechnicianId("tech-1"))
    command = RecordPhotoDuplicateSuspected(
        finding_id=FindingId("finding-1"),
        new_batch_id=BatchId("batch-new"),
        matched_batch_id=BatchId("batch-old"),
        new_machine_id=MachineId("vm-1"),
        matched_machine_id=MachineId("vm-2"),
        content_hash="abc",
        photo_index=0,
        detected_at=datetime(2026, 6, 5, tzinfo=UTC),
    )

    first = aggregate.record_photo_duplicate_suspected(command)
    second = aggregate.record_photo_duplicate_suspected(command)

    assert first is not None
    assert second is None
    assert aggregate.has_pending_findings() is True
    assert len(aggregate.collect_events()) == 1


def test_rehydrate_replays_photo_duplicate_suspected() -> None:
    aggregate = TechnicianAccountability.empty(TechnicianId("tech-1"))
    command = RecordPhotoDuplicateSuspected(
        finding_id=FindingId("finding-1"),
        new_batch_id=BatchId("batch-new"),
        matched_batch_id=BatchId("batch-old"),
        new_machine_id=MachineId("vm-1"),
        matched_machine_id=MachineId("vm-2"),
        content_hash="abc",
        photo_index=0,
        detected_at=datetime(2026, 6, 5, tzinfo=UTC),
    )
    event = aggregate.record_photo_duplicate_suspected(command)
    assert event is not None

    replayed = TechnicianAccountability.rehydrate(
        TechnicianId("tech-1"),
        [event],
    )
    assert replayed.has_pending_findings() is True
    assert replayed.collect_events() == []
