from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from beartype import beartype

from src.domain.ids import (
    BatchId,
    EventId,
    FindingId,
    MachineId,
    TechnicianId,
)
from src.domain.technician_accountability.events import (
    AccountabilityEvent,
    PhotoDuplicateReviewCompleted,
    PhotoDuplicateSuspected,
)


@beartype
@dataclass(frozen=True, slots=True)
class RecordPhotoDuplicateSuspected:
    finding_id: FindingId
    new_batch_id: BatchId
    matched_batch_id: BatchId
    new_machine_id: MachineId
    matched_machine_id: MachineId
    content_hash: str
    photo_index: int
    detected_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class CompletePhotoDuplicateReview:
    finding_id: FindingId
    verdict: str
    reviewed_at: datetime
    reviewer_note: str = ""


@beartype
@dataclass(slots=True)
class TechnicianAccountability:
    technician_id: TechnicianId
    _open_finding_ids: set[str] = field(default_factory=set, repr=False)
    _confirmed_photo_duplicates: int = field(default=0, repr=False)
    _false_positive_photo_duplicates: int = field(default=0, repr=False)
    _recorded_finding_ids: set[str] = field(default_factory=set, repr=False)
    _pending_events: list[AccountabilityEvent] = field(default_factory=list, repr=False)

    @classmethod
    @beartype
    def empty(cls, technician_id: TechnicianId) -> TechnicianAccountability:
        return cls(technician_id=technician_id)

    @classmethod
    @beartype
    def rehydrate(
        cls,
        technician_id: TechnicianId,
        events: list[AccountabilityEvent],
    ) -> TechnicianAccountability:
        aggregate = cls.empty(technician_id)
        for event in events:
            aggregate._apply(event)
        aggregate._pending_events.clear()
        return aggregate

    @beartype
    def record_photo_duplicate_suspected(
        self,
        command: RecordPhotoDuplicateSuspected,
    ) -> PhotoDuplicateSuspected | None:
        if command.finding_id.value in self._recorded_finding_ids:
            return None

        occurred_at = datetime.now(tz=UTC)
        event = PhotoDuplicateSuspected(
            event_id=EventId(str(uuid.uuid4())),
            finding_id=command.finding_id,
            technician_id=self.technician_id,
            new_batch_id=command.new_batch_id,
            matched_batch_id=command.matched_batch_id,
            new_machine_id=command.new_machine_id,
            matched_machine_id=command.matched_machine_id,
            content_hash=command.content_hash,
            photo_index=command.photo_index,
            detected_at=command.detected_at,
            occurred_at=occurred_at,
        )
        self._apply(event)
        self._pending_events.append(event)
        return event

    @beartype
    def complete_photo_duplicate_review(
        self,
        command: CompletePhotoDuplicateReview,
    ) -> PhotoDuplicateReviewCompleted | None:
        if command.finding_id.value not in self._open_finding_ids:
            return None
        if command.verdict not in {"confirmed", "false_positive"}:
            raise ValueError("verdict must be confirmed or false_positive")

        occurred_at = datetime.now(tz=UTC)
        event = PhotoDuplicateReviewCompleted(
            event_id=EventId(str(uuid.uuid4())),
            finding_id=command.finding_id,
            technician_id=self.technician_id,
            verdict=command.verdict,  # type: ignore[arg-type]
            reviewed_at=command.reviewed_at,
            occurred_at=occurred_at,
            reviewer_note=command.reviewer_note,
        )
        self._apply(event)
        self._pending_events.append(event)
        return event

    @beartype
    def has_pending_findings(self) -> bool:
        return bool(self._open_finding_ids)

    @beartype
    def confirmed_duplicate_count(self) -> int:
        return self._confirmed_photo_duplicates

    @beartype
    def collect_events(self) -> list[AccountabilityEvent]:
        return list(self._pending_events)

    @beartype
    def clear_pending_events(self) -> None:
        self._pending_events.clear()

    @beartype
    def _apply(self, event: AccountabilityEvent) -> None:
        if isinstance(event, PhotoDuplicateSuspected):
            self._recorded_finding_ids.add(event.finding_id.value)
            self._open_finding_ids.add(event.finding_id.value)
            return
        if isinstance(event, PhotoDuplicateReviewCompleted):
            self._open_finding_ids.discard(event.finding_id.value)
            if event.verdict == "confirmed":
                self._confirmed_photo_duplicates += 1
            else:
                self._false_positive_photo_duplicates += 1
