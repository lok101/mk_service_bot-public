from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.technician_warehouse import ObserveTechnicianWarehouseLoading
from src.domain.machine_operations.events import InventoryFormMoveSubmitted

_ALLOWED_PURPOSES = frozenset({"loading"})


@beartype
class FormSubmissionSnapshotMissingError(Exception):
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(f"Form submission snapshot was not found for event {event_id}")


@beartype
class FormSubmissionSnapshotPurposeError(NonRetryableOutboxError):
    def __init__(self, purpose: str, *, expected: str) -> None:
        self.purpose = purpose
        self.expected = expected
        super().__init__(
            f"Form submission snapshot purpose {purpose!r} does not match expected {expected!r}",
        )


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseLoadingHandler:
    form_submission_store: FormSubmissionStore
    observe_loading: ObserveTechnicianWarehouseLoading

    @beartype
    async def process(self, event: InventoryFormMoveSubmitted) -> None:
        snapshot = self.form_submission_store.get_by_event_id(event.event_id.value)
        if snapshot is None:
            raise FormSubmissionSnapshotMissingError(event.event_id.value)
        if snapshot.purpose not in _ALLOWED_PURPOSES:
            raise FormSubmissionSnapshotPurposeError(
                snapshot.purpose,
                expected=",".join(sorted(_ALLOWED_PURPOSES)),
            )
        self.observe_loading.execute(
            technician_id=event.technician_id,
            source_event_id=event.event_id.value,
            machine_id=event.machine_id,
            submitted_at=event.submitted_at,
            lines=snapshot.validated_lines,
        )
