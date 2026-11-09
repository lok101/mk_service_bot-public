from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from beartype import beartype
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.reference_data.location_roster import (
    LocationRosterConflict,
    LocationRosterEntry,
)
from src.config.location_roster import LocationRosterSettings
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection
from src.infrastructure.mongodb.location_roster import (
    LocationRosterCollection,
    _as_utc,
    _entry_from_document,
    _entry_to_document,
)


@beartype
@dataclass(frozen=True, slots=True)
class MongoLocationRosterDraftStore:
    draft_collection: LocationRosterCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        roster: LocationRosterSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoLocationRosterDraftStore:
        draft_collection = resolve_collection(
            mongo,
            collection_name=roster.draft_collection,
            owner="MongoLocationRosterDraftStore",
            client=client,
        )
        return cls(draft_collection=draft_collection)

    @beartype
    def get(self, machine_id: MachineId) -> LocationRosterEntry | None:
        document = self.draft_collection.find_one({"_id": machine_id.value})
        if document is None:
            return None
        return _entry_from_document(document)

    @beartype
    def list_all(self) -> tuple[LocationRosterEntry, ...]:
        items: list[LocationRosterEntry] = []
        for document in self.draft_collection.find({}):
            if isinstance(document, dict):
                items.append(_entry_from_document(document))
        items.sort(key=lambda entry: entry.machine_id.value)
        return tuple(items)

    @beartype
    def is_empty(self) -> bool:
        return int(self.draft_collection.count_documents({})) == 0

    @beartype
    def replace_all(self, entries: tuple[LocationRosterEntry, ...]) -> None:
        self.draft_collection.delete_many({})
        for entry in entries:
            self.draft_collection.replace_one(
                {"_id": entry.machine_id.value},
                _entry_to_document(entry),
                upsert=True,
            )

    @beartype
    def upsert(
        self,
        entry: LocationRosterEntry,
        *,
        expected_updated_at: datetime | None,
    ) -> LocationRosterEntry:
        document = _entry_to_document(entry)
        if expected_updated_at is None:
            try:
                self.draft_collection.insert_one(document)
            except DuplicateKeyError as error:
                raise LocationRosterConflict() from error
            return _entry_from_document(document)
        result = self.draft_collection.replace_one(
            {
                "_id": entry.machine_id.value,
                "updated_at": _as_utc(expected_updated_at),
            },
            document,
            upsert=False,
        )
        if int(getattr(result, "matched_count", 0)) == 0:
            raise LocationRosterConflict()
        return _entry_from_document(document)
