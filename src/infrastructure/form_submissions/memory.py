from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from beartype import beartype

from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionPurpose,
    FormSubmissionSnapshot,
    FrozenInventoryLine,
)
from src.domain.ids import MachineId, TechnicianId


@beartype
@dataclass
class InMemoryFormSubmissionStore:
    _by_submission_id: dict[str, FormSubmissionSnapshot] = field(default_factory=dict)
    _by_form_token: dict[tuple[str, FormSubmissionPurpose], str] = field(
        default_factory=dict,
    )
    _by_event_id: dict[str, str] = field(default_factory=dict)

    @beartype
    def save_pending(
        self,
        *,
        form_token: str,
        form_id: str,
        purpose: FormSubmissionPurpose,
        technician_id: TechnicianId,
        machine_id: MachineId | None,
        submitted_at: datetime,
        answers: tuple[FormAnswer, ...],
        validated_lines: tuple[FrozenInventoryLine, ...],
    ) -> FormSubmissionSnapshot:
        if not isinstance(submitted_at, datetime):
            raise TypeError("submitted_at must be datetime")

        existing_key = (form_token, purpose)
        existing_id = self._by_form_token.get(existing_key)
        if existing_id is not None:
            existing = self._by_submission_id[existing_id]
            if existing.status == "accepted":
                return existing
            # pending: last-write-wins refresh of the in-flight payload; rejected: reactivate.
            if existing.status in {"pending", "rejected"}:
                return self._refresh_to_pending_submission(
                    existing,
                    form_id=form_id,
                    submitted_at=submitted_at,
                    answers=answers,
                    validated_lines=validated_lines,
                )

        submission_id = str(uuid4())
        snapshot = FormSubmissionSnapshot(
            submission_id=submission_id,
            form_token=form_token,
            form_id=form_id,
            purpose=purpose,
            technician_id=technician_id,
            machine_id=machine_id,
            submitted_at=submitted_at,
            answers=answers,
            validated_lines=validated_lines,
            status="pending",
        )
        self._by_submission_id[submission_id] = snapshot
        self._by_form_token[existing_key] = submission_id
        return snapshot

    @beartype
    def _refresh_to_pending_submission(
        self,
        existing: FormSubmissionSnapshot,
        *,
        form_id: str,
        submitted_at: datetime,
        answers: tuple[FormAnswer, ...],
        validated_lines: tuple[FrozenInventoryLine, ...],
    ) -> FormSubmissionSnapshot:
        updated = FormSubmissionSnapshot(
            submission_id=existing.submission_id,
            form_token=existing.form_token,
            form_id=form_id,
            purpose=existing.purpose,
            technician_id=existing.technician_id,
            machine_id=existing.machine_id,
            submitted_at=submitted_at,
            answers=answers,
            validated_lines=validated_lines,
            status="pending",
            rejection_reason=None,
            warehouse_inventory_baseline=None,
        )
        self._by_submission_id[existing.submission_id] = updated
        return updated

    @beartype
    def mark_accepted(
        self,
        submission_id: str,
        *,
        event_id: str,
        occurred_at: datetime,
        revision_id: str | None = None,
        warehouse_inventory_baseline: bool | None = None,
    ) -> FormSubmissionSnapshot:
        snapshot = self._require_snapshot(submission_id)
        updated = FormSubmissionSnapshot(
            submission_id=snapshot.submission_id,
            form_token=snapshot.form_token,
            form_id=snapshot.form_id,
            purpose=snapshot.purpose,
            technician_id=snapshot.technician_id,
            machine_id=snapshot.machine_id,
            submitted_at=snapshot.submitted_at,
            answers=snapshot.answers,
            validated_lines=snapshot.validated_lines,
            status="accepted",
            event_id=event_id,
            occurred_at=occurred_at,
            revision_id=revision_id,
            rejection_reason=None,
            warehouse_inventory_baseline=warehouse_inventory_baseline,
        )
        self._by_submission_id[submission_id] = updated
        self._by_event_id[event_id] = submission_id
        return updated

    @beartype
    def mark_rejected(
        self,
        submission_id: str,
        *,
        reason: str,
    ) -> FormSubmissionSnapshot:
        snapshot = self._require_snapshot(submission_id)
        updated = FormSubmissionSnapshot(
            submission_id=snapshot.submission_id,
            form_token=snapshot.form_token,
            form_id=snapshot.form_id,
            purpose=snapshot.purpose,
            technician_id=snapshot.technician_id,
            machine_id=snapshot.machine_id,
            submitted_at=snapshot.submitted_at,
            answers=snapshot.answers,
            validated_lines=snapshot.validated_lines,
            status="rejected",
            rejection_reason=reason,
        )
        self._by_submission_id[submission_id] = updated
        return updated

    @beartype
    def get_by_event_id(self, event_id: str) -> FormSubmissionSnapshot | None:
        submission_id = self._by_event_id.get(event_id)
        if submission_id is None:
            return None
        return self._by_submission_id.get(submission_id)

    @beartype
    def get_by_form_token(
        self,
        form_token: str,
        purpose: FormSubmissionPurpose,
    ) -> FormSubmissionSnapshot | None:
        submission_id = self._by_form_token.get((form_token, purpose))
        if submission_id is None:
            return None
        return self._by_submission_id.get(submission_id)

    @beartype
    def _require_snapshot(self, submission_id: str) -> FormSubmissionSnapshot:
        try:
            return self._by_submission_id[submission_id]
        except KeyError as error:
            raise ValueError(f"Form submission {submission_id!r} was not found") from error
