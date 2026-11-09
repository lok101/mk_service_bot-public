from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.technician_accountability.executor import TechnicianAccountabilityExecutor
from src.domain.ids import BatchId, FindingId, MachineId, TechnicianId
from src.domain.technician_accountability import (
    RecordPhotoDuplicateSuspected,
    TechnicianAccountability,
)
from src.domain.technician_accountability.events import PhotoDuplicateSuspected


@beartype
@dataclass(frozen=True, slots=True)
class RecordPhotoDuplicateSuspectedService:
    executor: TechnicianAccountabilityExecutor

    @beartype
    def execute(
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
    ) -> PhotoDuplicateSuspected | None:
        command = RecordPhotoDuplicateSuspected(
            finding_id=finding_id,
            new_batch_id=new_batch_id,
            matched_batch_id=matched_batch_id,
            new_machine_id=new_machine_id,
            matched_machine_id=matched_machine_id,
            content_hash=content_hash,
            photo_index=photo_index,
            detected_at=detected_at,
        )

        def apply(aggregate: TechnicianAccountability) -> PhotoDuplicateSuspected | None:
            return aggregate.record_photo_duplicate_suspected(command)

        return self.executor.execute(technician_id, apply)
