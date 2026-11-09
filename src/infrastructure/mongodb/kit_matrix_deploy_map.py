from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.snack_loading.ports import KitMatrixDeployMapRow, KitMatrixDeployMapStore
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class KitMatrixDeployMapCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoKitMatrixDeployMapStore(KitMatrixDeployMapStore):
    _collection: KitMatrixDeployMapCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: KitMatrixDeployMapCollection,
    ) -> MongoKitMatrixDeployMapStore:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoKitMatrixDeployMapStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.kit_matrix_deploy_map_collection,
            owner="MongoKitMatrixDeployMapStore",
            client=client,
        )
        return cls.from_collection(cast(KitMatrixDeployMapCollection, collection))

    @beartype
    def upsert(
        self,
        *,
        kit_matrix_id: int,
        logical_matrix_name: str,
        machine_code: str,
        vending_machine_id: int | None,
        kit_matrix_name: str | None,
        applied_at: datetime | None = None,
    ) -> None:
        stamped = applied_at if applied_at is not None else datetime.now(UTC)
        self._collection.replace_one(
            {"_id": kit_matrix_id},
            {
                "_id": kit_matrix_id,
                "kit_matrix_id": kit_matrix_id,
                "logical_matrix_name": logical_matrix_name,
                "machine_code": machine_code,
                "vending_machine_id": vending_machine_id,
                "kit_matrix_name": kit_matrix_name,
                "applied_at": stamped,
            },
            upsert=True,
        )

    @beartype
    def get(self, kit_matrix_id: int) -> KitMatrixDeployMapRow | None:
        document = self._collection.find_one({"_id": kit_matrix_id})
        if document is None:
            return None
        return KitMatrixDeployMapRow(
            kit_matrix_id=int(document["kit_matrix_id"]),
            logical_matrix_name=str(document["logical_matrix_name"]),
            machine_code=str(document["machine_code"]),
            vending_machine_id=(
                int(document["vending_machine_id"])
                if document.get("vending_machine_id") is not None
                else None
            ),
            kit_matrix_name=(
                str(document["kit_matrix_name"])
                if document.get("kit_matrix_name") is not None
                else None
            ),
            applied_at=cast(datetime | None, document.get("applied_at")),
        )
