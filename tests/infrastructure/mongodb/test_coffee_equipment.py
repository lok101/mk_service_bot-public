from __future__ import annotations

import mongomock
import pytest
from pydantic import ValidationError

from src.application.master_data import MachineKind, MachineStatus, MasterMachine
from src.application.master_data.coffee_equipment import CoffeeMachineModel, StandColor, StandType
from src.config.master_data import MasterDataSettings
from src.domain.ids import MachineId
from src.infrastructure.mongodb.coffee_equipment import (
    MongoCoffeeMachineModelStore,
    MongoStandColorStore,
    MongoStandTypeStore,
)
from src.infrastructure.mongodb.master_data import _machine_from_document, _machine_to_document


def test_coffee_equipment_collection_defaults() -> None:
    settings = MasterDataSettings()
    assert settings.coffee_machine_models_collection == "master_coffee_machine_models"
    assert settings.stand_types_collection == "master_stand_types"
    assert settings.stand_colors_collection == "master_stand_colors"


@pytest.mark.parametrize(
    ("env_name",),
    [
        ("MONGODB_MASTER_COFFEE_MACHINE_MODELS_COLLECTION",),
        ("MONGODB_MASTER_STAND_TYPES_COLLECTION",),
        ("MONGODB_MASTER_STAND_COLORS_COLLECTION",),
    ],
)
def test_coffee_equipment_blank_collection_rejected(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
) -> None:
    monkeypatch.setenv(env_name, "   ")
    with pytest.raises(ValidationError):
        MasterDataSettings()


def test_coffee_equipment_mongo_roundtrip() -> None:
    client = mongomock.MongoClient()
    database = client["mk"]
    models = MongoCoffeeMachineModelStore(database["models"])
    stand_types = MongoStandTypeStore(database["types"])
    colors = MongoStandColorStore(database["colors"])
    models.upsert(CoffeeMachineModel(model_id="1", name="JL", floor_standing=True))
    stand_types.upsert(StandType(stand_type_id="2", name="Новый"))
    colors.upsert(StandColor(stand_color_id="3", name="Чёрный"))
    assert models.get("1") == CoffeeMachineModel(model_id="1", name="JL", floor_standing=True)
    assert stand_types.list_all() == (StandType(stand_type_id="2", name="Новый"),)
    assert colors.get("3") == StandColor(stand_color_id="3", name="Чёрный")

    machine = MasterMachine(
        machine_id=MachineId("101"),
        kind=MachineKind.COFFEE,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
        coffee_machine_model_id="1",
        stand_type_id="2",
        stand_color_id="3",
    )
    restored = _machine_from_document(_machine_to_document(machine))
    assert restored == machine


def test_coffee_equipment_machine_document_without_keys() -> None:
    machine = _machine_from_document(
        {
            "_id": "101",
            "kind": "coffee",
            "status": "active_on_site",
            "label": None,
        }
    )
    assert machine.coffee_machine_model_id is None
    assert machine.stand_type_id is None
    assert machine.stand_color_id is None
    assert machine.include_in_visit_photo_review is True
