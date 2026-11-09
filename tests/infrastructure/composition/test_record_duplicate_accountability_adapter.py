from __future__ import annotations

from datetime import UTC, datetime

from src.application.photo_integrity.ports import PhotoDuplicateAccountabilityRecorder
from src.application.technician_accountability.executor import TechnicianAccountabilityExecutor
from src.application.technician_accountability.record_duplicate import (
    RecordPhotoDuplicateSuspectedService,
)
from src.domain.ids import BatchId, FindingId, MachineId, TechnicianId
from src.infrastructure.composition.record_duplicate_accountability_adapter import (
    RecordPhotoDuplicateAccountabilityAdapter,
)
from src.infrastructure.technician_accountability.memory import (
    InMemoryTechnicianAccountabilityEventStore,
    InMemoryTechnicianAccountabilityRepository,
)

_TECH = TechnicianId("tech-a")


def test_adapter_records_event_and_satisfies_protocol() -> None:
    event_store = InMemoryTechnicianAccountabilityEventStore()
    repository = InMemoryTechnicianAccountabilityRepository(event_store=event_store)
    adapter = RecordPhotoDuplicateAccountabilityAdapter(
        service=RecordPhotoDuplicateSuspectedService(
            executor=TechnicianAccountabilityExecutor(repository=repository),
        ),
    )

    assert isinstance(adapter, PhotoDuplicateAccountabilityRecorder)

    result = adapter.record_duplicate_suspected(
        technician_id=_TECH,
        finding_id=FindingId("finding-1"),
        new_batch_id=BatchId("batch-new"),
        matched_batch_id=BatchId("batch-old"),
        new_machine_id=MachineId("vm-02"),
        matched_machine_id=MachineId("vm-01"),
        content_hash="a" * 64,
        photo_index=0,
        detected_at=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
    )

    assert result is None
    assert len(event_store.get_events_for_technician(_TECH)) == 1
