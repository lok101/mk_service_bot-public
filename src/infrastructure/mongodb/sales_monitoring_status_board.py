from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.sales_monitoring.status_board_pointer import (
    STATUS_BOARD_POINTER_ID,
    StatusBoardPointer,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class StatusBoardPointerCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> object: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
@dataclass(frozen=True, slots=True)
class MongoStatusBoardPointerStore:
    _collection: StatusBoardPointerCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: StatusBoardPointerCollection,
    ) -> MongoStatusBoardPointerStore:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoStatusBoardPointerStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.sales_monitoring_status_board_collection,
            owner="MongoStatusBoardPointerStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def load(self) -> StatusBoardPointer | None:
        document = self._collection.find_one({"_id": STATUS_BOARD_POINTER_ID})
        if document is None:
            return None
        chat_id = document.get("chat_id")
        message_id = document.get("message_id")
        posted_at = document.get("posted_at")
        last_text = document.get("last_text")
        if (
            not isinstance(chat_id, int)
            or not isinstance(message_id, int)
            or not isinstance(posted_at, datetime)
            or not isinstance(last_text, str)
        ):
            _LOGGER.error(
                "status_board_pointer_invalid",
                extra={"document_id": STATUS_BOARD_POINTER_ID},
            )
            return None
        return StatusBoardPointer(
            chat_id=chat_id,
            message_id=message_id,
            posted_at=_as_utc(posted_at),
            last_text=last_text,
        )

    @beartype
    def save(self, pointer: StatusBoardPointer) -> None:
        self._collection.replace_one(
            {"_id": STATUS_BOARD_POINTER_ID},
            {
                "_id": STATUS_BOARD_POINTER_ID,
                "chat_id": pointer.chat_id,
                "message_id": pointer.message_id,
                "posted_at": _as_utc(pointer.posted_at),
                "last_text": pointer.last_text,
            },
            upsert=True,
        )
