from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.move_command import (
    MicromarketLoadingMoveCommand,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class MicromarketLoadingMoveCommandCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> Any: ...


def _positions_to_doc(
    positions: tuple[tuple[str, Decimal], ...],
) -> list[dict[str, str]]:
    return [{"catalog_code": code, "qty": str(qty)} for code, qty in positions]


def _positions_from_doc(raw: object) -> tuple[tuple[str, Decimal], ...]:
    if not isinstance(raw, list):
        return ()
    out: list[tuple[str, Decimal]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = item.get("catalog_code")
        qty = item.get("qty")
        if not isinstance(code, str) or not isinstance(qty, str):
            continue
        out.append((code, Decimal(qty)))
    return tuple(out)


@beartype
def command_to_document(command: MicromarketLoadingMoveCommand) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_id": command.command_id,
        "kind": command.kind,
        "status": command.status,
    }
    if command.order_id is not None:
        doc["order_id"] = command.order_id
    if command.machine_code is not None:
        doc["machine_code"] = command.machine_code
    if command.positions:
        doc["positions"] = _positions_to_doc(command.positions)
    if command.move_id is not None:
        doc["move_id"] = command.move_id
    if command.stale is not None:
        doc["stale"] = command.stale
    if command.error is not None:
        doc["error"] = command.error
    return doc


@beartype
def command_from_document(document: dict[str, Any]) -> MicromarketLoadingMoveCommand:
    command_id = document["_id"]
    if not isinstance(command_id, str):
        raise TypeError("command_id must be str")
    kind = document.get("kind")
    status = document.get("status")
    if kind not in ("create", "delete", "stale_check"):
        raise ValueError(f"unknown move command kind: {kind!r}")
    if status not in ("pending", "succeeded", "failed"):
        raise ValueError(f"unknown move command status: {status!r}")
    order_id = document.get("order_id")
    machine_code = document.get("machine_code")
    move_id = document.get("move_id")
    stale = document.get("stale")
    error = document.get("error")
    return MicromarketLoadingMoveCommand(
        command_id=command_id,
        kind=kind,
        status=status,
        order_id=order_id if isinstance(order_id, str) else None,
        machine_code=machine_code if isinstance(machine_code, str) else None,
        positions=_positions_from_doc(document.get("positions")),
        move_id=move_id if isinstance(move_id, str) else None,
        stale=stale if isinstance(stale, bool) else None,
        error=error if isinstance(error, str) else None,
    )


@beartype
class MongoMicromarketLoadingMoveCommandStore:
    def __init__(self, collection: MicromarketLoadingMoveCommandCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketLoadingMoveCommandStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_loading_move_commands_collection,
            owner="MongoMicromarketLoadingMoveCommandStore",
            client=client,
        )
        return cls(collection)

    @beartype
    def create_pending(self, command: MicromarketLoadingMoveCommand) -> None:
        if command.status != "pending":
            raise ValueError("create_pending expects status pending")
        self._collection.insert_one(command_to_document(command))

    @beartype
    def get(self, command_id: str) -> MicromarketLoadingMoveCommand | None:
        document = self._collection.find_one({"_id": command_id})
        if document is None:
            return None
        return command_from_document(document)

    @beartype
    def mark_succeeded(
        self,
        *,
        command_id: str,
        move_id: str | None = None,
        stale: bool | None = None,
    ) -> bool:
        update: dict[str, Any] = {"status": "succeeded"}
        if move_id is not None:
            update["move_id"] = move_id
        if stale is not None:
            update["stale"] = stale
        result = self._collection.update_one(
            {"_id": command_id, "status": "pending"},
            {"$set": update},
        )
        matched = getattr(result, "matched_count", 0)
        return matched == 1

    @beartype
    def mark_failed(self, *, command_id: str, error: str) -> bool:
        result = self._collection.update_one(
            {"_id": command_id, "status": "pending"},
            {"$set": {"status": "failed", "error": error}},
        )
        matched = getattr(result, "matched_count", 0)
        return matched == 1


@beartype
class InMemoryMicromarketLoadingMoveCommandStore:
    def __init__(self) -> None:
        self._commands: dict[str, MicromarketLoadingMoveCommand] = {}

    @beartype
    def create_pending(self, command: MicromarketLoadingMoveCommand) -> None:
        if command.command_id in self._commands:
            raise ValueError(f"command already exists: {command.command_id}")
        self._commands[command.command_id] = command

    @beartype
    def get(self, command_id: str) -> MicromarketLoadingMoveCommand | None:
        return self._commands.get(command_id)

    @beartype
    def mark_succeeded(
        self,
        *,
        command_id: str,
        move_id: str | None = None,
        stale: bool | None = None,
    ) -> bool:
        existing = self._commands.get(command_id)
        if existing is None or existing.status != "pending":
            return False
        self._commands[command_id] = MicromarketLoadingMoveCommand(
            command_id=existing.command_id,
            kind=existing.kind,
            status="succeeded",
            order_id=existing.order_id,
            machine_code=existing.machine_code,
            positions=existing.positions,
            move_id=move_id if move_id is not None else existing.move_id,
            stale=stale if stale is not None else existing.stale,
        )
        return True

    @beartype
    def mark_failed(self, *, command_id: str, error: str) -> bool:
        existing = self._commands.get(command_id)
        if existing is None or existing.status != "pending":
            return False
        self._commands[command_id] = MicromarketLoadingMoveCommand(
            command_id=existing.command_id,
            kind=existing.kind,
            status="failed",
            order_id=existing.order_id,
            machine_code=existing.machine_code,
            positions=existing.positions,
            error=error,
        )
        return True
