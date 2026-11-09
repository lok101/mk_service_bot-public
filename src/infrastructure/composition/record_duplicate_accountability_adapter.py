from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.technician_accountability.record_duplicate import (
    RecordPhotoDuplicateSuspectedService,
)
from src.domain.ids import BatchId, FindingId, MachineId, TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class RecordPhotoDuplicateAccountabilityAdapter:
    service: RecordPhotoDuplicateSuspectedService

    @beartype
    def record_duplicate_suspected(
        self,
        *,
        technician_id: TechnicianId,
        finding_id: FindingId,
        new_batch_id: BatchId,
        matched_batch_id: BatchId,
        new_machine_id: MachineId,
        matched_machine_id: MachineId,
        content_hash: str,
        photo_index: int,
        detected_at: datetime,
    ) -> None:
        self.service.execute(
            technician_id=technician_id,
            finding_id=finding_id,
            new_batch_id=new_batch_id,
            matched_batch_id=matched_batch_id,
            new_machine_id=new_machine_id,
            matched_machine_id=matched_machine_id,
            content_hash=content_hash,
            photo_index=photo_index,
            detected_at=detected_at,
        )
