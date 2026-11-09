from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.config.mongodb import MongoSettings
from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionPurpose,
    FormSubmissionSnapshot,
    FrozenInventoryLine,
)
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.form_submission_codec import (
    document_to_validated_lines,
    frozen_line_to_document,
)


@runtime_checkable
class FormSubmissionsCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> object: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoFormSubmissionStore:
    _collection: FormSubmissionsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: FormSubmissionsCollection,
    ) -> MongoFormSubmissionStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoFormSubmissionStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.form_submissions_collection,
            owner="MongoFormSubmissionStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("form_token", ASCENDING), ("purpose", ASCENDING)],
            unique=True,
            name="form_submission_token_purpose_unique",
        )
        self._collection.create_index(
            "event_id",
            unique=True,
            sparse=True,
            name="form_submission_event_id_unique",
        )

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
        existing = self.get_by_form_token(form_token, purpose)
        if existing is not None:
            resolved = self._resolve_existing_for_save_pending(
                existing,
                form_id=form_id,
                submitted_at=submitted_at,
                answers=answers,
                validated_lines=validated_lines,
            )
            if resolved is not None:
                return resolved

        submission_id = str(uuid4())
        document = _snapshot_to_document(
            FormSubmissionSnapshot(
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
            ),
        )
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError:
            existing = self.get_by_form_token(form_token, purpose)
            if existing is None:
                raise
            resolved = self._resolve_existing_for_save_pending(
                existing,
                form_id=form_id,
                submitted_at=submitted_at,
                answers=answers,
                validated_lines=validated_lines,
            )
            if resolved is not None:
                return resolved
            return existing

        return _document_to_snapshot(document)

    @beartype
    def _resolve_existing_for_save_pending(
        self,
        existing: FormSubmissionSnapshot,
        *,
        form_id: str,
        submitted_at: datetime,
        answers: tuple[FormAnswer, ...],
        validated_lines: tuple[FrozenInventoryLine, ...],
    ) -> FormSubmissionSnapshot | None:
        if existing.status == "accepted":
            return existing
        # pending: last-write-wins refresh of the in-flight payload; rejected: reactivate.
        if existing.status in {"pending", "rejected"}:
            return self._refresh_to_pending_submission(
                existing.submission_id,
                form_id=form_id,
                submitted_at=submitted_at,
                answers=answers,
                validated_lines=validated_lines,
            )
        return None

    @beartype
    def _refresh_to_pending_submission(
        self,
        submission_id: str,
        *,
        form_id: str,
        submitted_at: datetime,
        answers: tuple[FormAnswer, ...],
        validated_lines: tuple[FrozenInventoryLine, ...],
    ) -> FormSubmissionSnapshot:
        self._collection.update_one(
            {"submission_id": submission_id},
            {
                "$set": {
                    "status": "pending",
                    "form_id": form_id,
                    "submitted_at": submitted_at,
                    "answers": [
                        {"title": answer.title, "value": answer.value} for answer in answers
                    ],
                    "validated_lines": [frozen_line_to_document(line) for line in validated_lines],
                    "rejection_reason": None,
                },
            },
        )
        return self._require_snapshot(submission_id)

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
        update_fields: dict[str, Any] = {
            "status": "accepted",
            "event_id": event_id,
            "occurred_at": occurred_at,
            "rejection_reason": None,
        }
        if revision_id is not None:
            update_fields["revision_id"] = revision_id
        if warehouse_inventory_baseline is not None:
            update_fields["warehouse_inventory_baseline"] = warehouse_inventory_baseline

        self._collection.update_one(
            {"submission_id": submission_id},
            {"$set": update_fields},
        )
        return self._require_snapshot(submission_id)

    @beartype
    def mark_rejected(
        self,
        submission_id: str,
        *,
        reason: str,
    ) -> FormSubmissionSnapshot:
        self._collection.update_one(
            {"submission_id": submission_id},
            {
                "$set": {
                    "status": "rejected",
                    "rejection_reason": reason,
                },
            },
        )
        return self._require_snapshot(submission_id)

    @beartype
    def get_by_event_id(self, event_id: str) -> FormSubmissionSnapshot | None:
        document = self._collection.find_one({"event_id": event_id})
        if document is None:
            return None
        return _document_to_snapshot(document)

    @beartype
    def get_by_form_token(
        self,
        form_token: str,
        purpose: FormSubmissionPurpose,
    ) -> FormSubmissionSnapshot | None:
        document = self._collection.find_one(
            {"form_token": form_token, "purpose": purpose},
        )
        if document is None:
            return None
        return _document_to_snapshot(document)

    @beartype
    def _require_snapshot(self, submission_id: str) -> FormSubmissionSnapshot:
        document = self._collection.find_one({"submission_id": submission_id})
        if document is None:
            raise ValueError(f"Form submission {submission_id!r} was not found")
        return _document_to_snapshot(document)


@beartype
def _snapshot_to_document(snapshot: FormSubmissionSnapshot) -> dict[str, Any]:
    # Omit event_id when unset: unique sparse index indexes null, so event_id:null
    # would allow only one pending/rejected submission in the whole collection.
    document: dict[str, Any] = {
        "submission_id": snapshot.submission_id,
        "form_token": snapshot.form_token,
        "form_id": snapshot.form_id,
        "purpose": snapshot.purpose,
        "technician_id": snapshot.technician_id.value,
        "machine_id": snapshot.machine_id.value if snapshot.machine_id is not None else None,
        "submitted_at": snapshot.submitted_at,
        "answers": [{"title": answer.title, "value": answer.value} for answer in snapshot.answers],
        "validated_lines": [frozen_line_to_document(line) for line in snapshot.validated_lines],
        "status": snapshot.status,
        "occurred_at": snapshot.occurred_at,
        "revision_id": snapshot.revision_id,
        "rejection_reason": snapshot.rejection_reason,
        "warehouse_inventory_baseline": snapshot.warehouse_inventory_baseline,
    }
    if snapshot.event_id is not None:
        document["event_id"] = snapshot.event_id
    return document


@beartype
def _document_to_snapshot(document: dict[str, Any]) -> FormSubmissionSnapshot:
    raw_answers = document.get("answers", [])
    if not isinstance(raw_answers, list):
        raise ValueError("Form submission answers must be a list")

    answers: list[FormAnswer] = []
    for raw_answer in raw_answers:
        if not isinstance(raw_answer, dict):
            raise ValueError("Form submission answer must be an object")
        title = raw_answer.get("title")
        value = raw_answer.get("value")
        if not isinstance(title, str) or not isinstance(value, str):
            raise ValueError("Form submission answer must have title and value strings")
        answers.append(FormAnswer(title=title, value=value))

    submitted_at = document.get("submitted_at")
    if not isinstance(submitted_at, datetime):
        raise ValueError("Form submission submitted_at must be datetime")

    purpose = document.get("purpose")
    status = document.get("status")
    if purpose not in {"revision", "loading", "technician_warehouse_inventory"}:
        raise ValueError("Form submission purpose is invalid")
    if status not in {"pending", "accepted", "rejected"}:
        raise ValueError("Form submission status is invalid")

    technician_id = document.get("technician_id")
    machine_id = document.get("machine_id")
    submission_id = document.get("submission_id")
    form_token = document.get("form_token")
    form_id = document.get("form_id")
    if (
        not isinstance(technician_id, str)
        or not isinstance(submission_id, str)
        or not isinstance(form_token, str)
        or not isinstance(form_id, str)
    ):
        raise ValueError("Form submission document has invalid identifiers")

    resolved_machine_id: MachineId | None
    if purpose == "technician_warehouse_inventory":
        if machine_id is not None and not isinstance(machine_id, str):
            raise ValueError("Form submission document has invalid machine_id")
        resolved_machine_id = MachineId(machine_id) if isinstance(machine_id, str) else None
    else:
        if not isinstance(machine_id, str):
            raise ValueError("Form submission document has invalid machine_id")
        resolved_machine_id = MachineId(machine_id)

    event_id = document.get("event_id")
    occurred_at = document.get("occurred_at")
    revision_id = document.get("revision_id")
    rejection_reason = document.get("rejection_reason")
    warehouse_inventory_baseline = document.get("warehouse_inventory_baseline")

    resolved_occurred_at = occurred_at if isinstance(occurred_at, datetime) else None
    resolved_baseline: bool | None
    if warehouse_inventory_baseline is None:
        resolved_baseline = None
    elif isinstance(warehouse_inventory_baseline, bool):
        resolved_baseline = warehouse_inventory_baseline
    else:
        raise ValueError("Form submission warehouse_inventory_baseline must be a boolean")

    return FormSubmissionSnapshot(
        submission_id=submission_id,
        form_token=form_token,
        form_id=form_id,
        purpose=purpose,
        technician_id=TechnicianId(technician_id),
        machine_id=resolved_machine_id,
        submitted_at=submitted_at,
        answers=tuple(answers),
        validated_lines=document_to_validated_lines(document),
        status=status,
        event_id=event_id if isinstance(event_id, str) else None,
        occurred_at=resolved_occurred_at,
        revision_id=revision_id if isinstance(revision_id, str) else None,
        rejection_reason=(rejection_reason if isinstance(rejection_reason, str) else None),
        warehouse_inventory_baseline=resolved_baseline,
    )
