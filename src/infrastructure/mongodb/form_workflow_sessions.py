from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient

from src.config.mongodb import MongoSettings
from src.domain.form_submission import FormSubmissionPurpose
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.mongodb.connection import resolve_collection
from src.interfaces.telegram.form_workflow import FormWorkflowSession


@runtime_checkable
class FormWorkflowSessionsCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool,
    ) -> object: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find_one_and_delete(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoFormWorkflowSessionStore:
    _collection: FormWorkflowSessionsCollection
    _ttl_seconds: int

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: FormWorkflowSessionsCollection,
        *,
        ttl_seconds: int,
    ) -> MongoFormWorkflowSessionStore:
        store = cls(_collection=collection, _ttl_seconds=ttl_seconds)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        ttl_seconds: int,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoFormWorkflowSessionStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.form_workflow_sessions_collection,
            owner="MongoFormWorkflowSessionStore",
            client=client,
        )
        return cls.from_collection(collection, ttl_seconds=ttl_seconds)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [
                ("technician_id", ASCENDING),
                ("machine_id", ASCENDING),
                ("purpose", ASCENDING),
            ],
            unique=True,
            name="form_workflow_session_unique",
        )
        self._collection.create_index(
            "registered_at",
            expireAfterSeconds=self._ttl_seconds,
            name="form_workflow_session_ttl",
        )

    @beartype
    def upsert(self, session: FormWorkflowSession) -> None:
        self._collection.replace_one(
            _filter_for_session(session.technician_id, session.machine_id, session.purpose),
            _session_to_document(session),
            upsert=True,
        )

    @beartype
    def find(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
        purpose: FormSubmissionPurpose,
    ) -> FormWorkflowSession | None:
        document = self._collection.find_one(
            _filter_for_session(technician_id, machine_id, purpose),
        )
        if document is None:
            return None
        return _document_to_session(document)

    @beartype
    def remove(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
        purpose: FormSubmissionPurpose,
    ) -> FormWorkflowSession | None:
        document = self._collection.find_one_and_delete(
            _filter_for_session(technician_id, machine_id, purpose),
        )
        if document is None:
            return None
        return _document_to_session(document)


@beartype
def _filter_for_session(
    technician_id: TechnicianId,
    machine_id: MachineId,
    purpose: FormSubmissionPurpose,
) -> dict[str, str]:
    return {
        "technician_id": technician_id.value,
        "machine_id": machine_id.value,
        "purpose": purpose,
    }


@beartype
def _session_to_document(session: FormWorkflowSession) -> dict[str, Any]:
    return {
        "technician_id": session.technician_id.value,
        "machine_id": session.machine_id.value,
        "purpose": session.purpose,
        "chat_id": session.chat_id,
        "telegram_user_id": session.telegram_user_id,
        "machine_name": session.machine_name,
        "maintenance_screen": session.maintenance_screen,
        "registered_at": session.registered_at,
        "dialog_message_id": session.dialog_message_id,
    }


@beartype
def _document_to_session(document: dict[str, Any]) -> FormWorkflowSession:
    technician_id = document.get("technician_id")
    machine_id = document.get("machine_id")
    purpose = document.get("purpose")
    chat_id = document.get("chat_id")
    telegram_user_id = document.get("telegram_user_id")
    machine_name = document.get("machine_name")
    maintenance_screen = document.get("maintenance_screen")
    registered_at = document.get("registered_at")
    dialog_message_id = document.get("dialog_message_id")

    if (
        not isinstance(technician_id, str)
        or not isinstance(machine_id, str)
        or purpose not in {"revision", "loading"}
        or not isinstance(chat_id, int)
        or not isinstance(telegram_user_id, int)
        or not isinstance(machine_name, str)
        or maintenance_screen not in {"maintenance", "admin_maintenance"}
        or not isinstance(registered_at, datetime)
    ):
        raise ValueError("Form workflow session document has invalid shape")

    resolved_message_id: int | None
    if dialog_message_id is None:
        resolved_message_id = None
    elif isinstance(dialog_message_id, int):
        resolved_message_id = dialog_message_id
    else:
        raise ValueError("Form workflow session document has invalid shape")

    return FormWorkflowSession(
        chat_id=chat_id,
        telegram_user_id=telegram_user_id,
        technician_id=TechnicianId(technician_id),
        machine_id=MachineId(machine_id),
        machine_name=machine_name,
        purpose=purpose,
        maintenance_screen=maintenance_screen,
        registered_at=registered_at,
        dialog_message_id=resolved_message_id,
    )
