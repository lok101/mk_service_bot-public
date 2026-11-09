from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.master_data.coffee_equipment import (
    CoffeeEquipmentCatalogs,
    CoffeeMachineModel,
    StandColor,
    StandType,
)
from src.config.master_data import MasterDataSettings
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import (
    MongoCollectionSource,
    MongoDatabaseSource,
    resolve_collection,
)


def _require_name(document: dict[str, Any]) -> str:
    name = document.get("name")
    if not isinstance(name, str):
        raise ValueError("catalog name must be str")
    return name


@beartype
class MongoCoffeeMachineModelStore:
    def __init__(self, collection: MongoCollectionSource) -> None:
        self._collection = collection

    def get(self, model_id: str) -> CoffeeMachineModel | None:
        document = self._collection.find_one({"_id": model_id})
        if document is None:
            return None
        floor_standing = document.get("floor_standing", False)
        if not isinstance(floor_standing, bool):
            raise ValueError("floor_standing must be bool")
        return CoffeeMachineModel(
            model_id=model_id,
            name=_require_name(document),
            floor_standing=floor_standing,
        )

    def upsert(self, model: CoffeeMachineModel) -> None:
        self._collection.replace_one(
            {"_id": model.model_id},
            {
                "_id": model.model_id,
                "name": model.name,
                "floor_standing": model.floor_standing,
            },
            upsert=True,
        )

    def delete(self, model_id: str) -> None:
        self._collection.delete_one({"_id": model_id})

    def list_all(self) -> tuple[CoffeeMachineModel, ...]:
        rows: list[CoffeeMachineModel] = []
        for document in self._collection.find({}):
            if not isinstance(document, dict):
                raise ValueError("catalog document must be an object")
            model_id = document.get("_id")
            if not isinstance(model_id, str):
                raise ValueError("model_id must be str")
            loaded = self.get(model_id)
            if loaded is not None:
                rows.append(loaded)
        return tuple(rows)


@beartype
class MongoStandTypeStore:
    def __init__(self, collection: MongoCollectionSource) -> None:
        self._collection = collection

    def get(self, stand_type_id: str) -> StandType | None:
        document = self._collection.find_one({"_id": stand_type_id})
        if document is None:
            return None
        return StandType(stand_type_id=stand_type_id, name=_require_name(document))

    def upsert(self, stand_type: StandType) -> None:
        self._collection.replace_one(
            {"_id": stand_type.stand_type_id},
            {"_id": stand_type.stand_type_id, "name": stand_type.name},
            upsert=True,
        )

    def delete(self, stand_type_id: str) -> None:
        self._collection.delete_one({"_id": stand_type_id})

    def list_all(self) -> tuple[StandType, ...]:
        rows: list[StandType] = []
        for document in self._collection.find({}):
            if not isinstance(document, dict):
                raise ValueError("catalog document must be an object")
            stand_type_id = document.get("_id")
            if not isinstance(stand_type_id, str):
                raise ValueError("stand_type_id must be str")
            loaded = self.get(stand_type_id)
            if loaded is not None:
                rows.append(loaded)
        return tuple(rows)


@beartype
class MongoStandColorStore:
    def __init__(self, collection: MongoCollectionSource) -> None:
        self._collection = collection

    def get(self, stand_color_id: str) -> StandColor | None:
        document = self._collection.find_one({"_id": stand_color_id})
        if document is None:
            return None
        return StandColor(stand_color_id=stand_color_id, name=_require_name(document))

    def upsert(self, stand_color: StandColor) -> None:
        self._collection.replace_one(
            {"_id": stand_color.stand_color_id},
            {"_id": stand_color.stand_color_id, "name": stand_color.name},
            upsert=True,
        )

    def delete(self, stand_color_id: str) -> None:
        self._collection.delete_one({"_id": stand_color_id})

    def list_all(self) -> tuple[StandColor, ...]:
        rows: list[StandColor] = []
        for document in self._collection.find({}):
            if not isinstance(document, dict):
                raise ValueError("catalog document must be an object")
            stand_color_id = document.get("_id")
            if not isinstance(stand_color_id, str):
                raise ValueError("stand_color_id must be str")
            loaded = self.get(stand_color_id)
            if loaded is not None:
                rows.append(loaded)
        return tuple(rows)


@beartype
def mongo_coffee_equipment_catalogs(
    mongo: MongoSettings,
    master_data: MasterDataSettings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource,
) -> CoffeeEquipmentCatalogs:
    return CoffeeEquipmentCatalogs(
        models=MongoCoffeeMachineModelStore(
            resolve_collection(
                mongo,
                collection_name=master_data.coffee_machine_models_collection,
                owner="MongoCoffeeMachineModelStore",
                client=client,
            ),
        ),
        stand_types=MongoStandTypeStore(
            resolve_collection(
                mongo,
                collection_name=master_data.stand_types_collection,
                owner="MongoStandTypeStore",
                client=client,
            ),
        ),
        stand_colors=MongoStandColorStore(
            resolve_collection(
                mongo,
                collection_name=master_data.stand_colors_collection,
                owner="MongoStandColorStore",
                client=client,
            ),
        ),
    )
