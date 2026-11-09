from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import NoReturn, Protocol, runtime_checkable

from beartype import beartype

from src.application.master_data.models import (
    MachineKind,
    MasterDataAuditRecord,
    MasterMachine,
)
from src.application.master_data.ports import MasterDataStores

COFFEE_MACHINE_MODEL_COUNTER_KEY = "coffee_machine_model"
STAND_TYPE_COUNTER_KEY = "stand_type"
STAND_COLOR_COUNTER_KEY = "stand_color"


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeMachineModel:
    model_id: str
    name: str
    floor_standing: bool


@beartype
@dataclass(frozen=True, slots=True)
class StandType:
    stand_type_id: str
    name: str


@beartype
@dataclass(frozen=True, slots=True)
class StandColor:
    stand_color_id: str
    name: str


@runtime_checkable
class CoffeeMachineModelStore(Protocol):
    @beartype
    def get(self, model_id: str) -> CoffeeMachineModel | None: ...

    @beartype
    def upsert(self, model: CoffeeMachineModel) -> None: ...

    @beartype
    def delete(self, model_id: str) -> None: ...

    @beartype
    def list_all(self) -> tuple[CoffeeMachineModel, ...]: ...


@runtime_checkable
class StandTypeStore(Protocol):
    @beartype
    def get(self, stand_type_id: str) -> StandType | None: ...

    @beartype
    def upsert(self, stand_type: StandType) -> None: ...

    @beartype
    def delete(self, stand_type_id: str) -> None: ...

    @beartype
    def list_all(self) -> tuple[StandType, ...]: ...


@runtime_checkable
class StandColorStore(Protocol):
    @beartype
    def get(self, stand_color_id: str) -> StandColor | None: ...

    @beartype
    def upsert(self, stand_color: StandColor) -> None: ...

    @beartype
    def delete(self, stand_color_id: str) -> None: ...

    @beartype
    def list_all(self) -> tuple[StandColor, ...]: ...


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeEquipmentCatalogs:
    models: CoffeeMachineModelStore
    stand_types: StandTypeStore
    stand_colors: StandColorStore


@beartype
@dataclass(slots=True)
class InMemoryCoffeeMachineModelStore:
    _by_id: dict[str, CoffeeMachineModel] = field(default_factory=dict)

    def get(self, model_id: str) -> CoffeeMachineModel | None:
        return self._by_id.get(model_id)

    def upsert(self, model: CoffeeMachineModel) -> None:
        self._by_id[model.model_id] = model

    def delete(self, model_id: str) -> None:
        self._by_id.pop(model_id, None)

    def list_all(self) -> tuple[CoffeeMachineModel, ...]:
        return tuple(self._by_id.values())


@beartype
@dataclass(slots=True)
class InMemoryStandTypeStore:
    _by_id: dict[str, StandType] = field(default_factory=dict)

    def get(self, stand_type_id: str) -> StandType | None:
        return self._by_id.get(stand_type_id)

    def upsert(self, stand_type: StandType) -> None:
        self._by_id[stand_type.stand_type_id] = stand_type

    def delete(self, stand_type_id: str) -> None:
        self._by_id.pop(stand_type_id, None)

    def list_all(self) -> tuple[StandType, ...]:
        return tuple(self._by_id.values())


@beartype
@dataclass(slots=True)
class InMemoryStandColorStore:
    _by_id: dict[str, StandColor] = field(default_factory=dict)

    def get(self, stand_color_id: str) -> StandColor | None:
        return self._by_id.get(stand_color_id)

    def upsert(self, stand_color: StandColor) -> None:
        self._by_id[stand_color.stand_color_id] = stand_color

    def delete(self, stand_color_id: str) -> None:
        self._by_id.pop(stand_color_id, None)

    def list_all(self) -> tuple[StandColor, ...]:
        return tuple(self._by_id.values())


def _reject(message: str, code: str) -> NoReturn:
    from src.application.master_data.commands import MasterDataCommandRejected

    raise MasterDataCommandRejected(message, code=code)


def _require_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        _reject("catalog name is empty", "catalog_name_invalid")
    return stripped


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@beartype
def apply_equipment_to_machine(
    machine: MasterMachine,
    catalogs: CoffeeEquipmentCatalogs,
    *,
    model_id: str | None,
    stand_type_id: str | None,
    stand_color_id: str | None,
) -> MasterMachine:
    model_id = _blank(model_id)
    stand_type_id = _blank(stand_type_id)
    stand_color_id = _blank(stand_color_id)
    if machine.kind is not MachineKind.COFFEE:
        if model_id or stand_type_id or stand_color_id:
            _reject(
                "equipment catalogs apply only to coffee machines",
                "equipment_catalog_not_for_kind",
            )
        return machine
    if model_id is None:
        if stand_type_id or stand_color_id:
            _reject("stand requires a coffee machine model", "stand_not_allowed")
        return replace(
            machine,
            coffee_machine_model_id=None,
            stand_type_id=None,
            stand_color_id=None,
        )
    model = catalogs.models.get(model_id)
    if model is None:
        _reject(f"unknown coffee machine model {model_id}", "unknown_catalog_entry")
    if model.floor_standing:
        stand_type_id = None
        stand_color_id = None
    elif stand_type_id is not None and catalogs.stand_types.get(stand_type_id) is None:
        _reject(f"unknown stand type {stand_type_id}", "unknown_catalog_entry")
    elif stand_color_id is not None and catalogs.stand_colors.get(stand_color_id) is None:
        _reject(f"unknown stand color {stand_color_id}", "unknown_catalog_entry")
    return replace(
        machine,
        coffee_machine_model_id=model_id,
        stand_type_id=stand_type_id,
        stand_color_id=stand_color_id,
    )


@beartype
@dataclass(slots=True)
class CoffeeEquipmentCommands:
    stores: MasterDataStores
    catalogs: CoffeeEquipmentCatalogs
    now_factory: Callable[[], datetime]

    def create_model(
        self,
        *,
        name: str,
        floor_standing: bool,
        actor_telegram_user_id: int,
    ) -> CoffeeMachineModel:
        normalized = _require_name(name)
        self._reject_duplicate_model(normalized, current_id=None)
        model_id = str(self.stores.counters.allocate_next(COFFEE_MACHINE_MODEL_COUNTER_KEY))
        model = CoffeeMachineModel(
            model_id=model_id,
            name=normalized,
            floor_standing=floor_standing,
        )
        self.catalogs.models.upsert(model)
        self._audit(
            "create_coffee_machine_model",
            {"model_id": model_id, "name": normalized, "floor_standing": str(floor_standing)},
            actor_telegram_user_id,
        )
        return model

    def save_model(
        self,
        *,
        model_id: str,
        name: str,
        floor_standing: bool,
        actor_telegram_user_id: int,
    ) -> CoffeeMachineModel:
        existing = self.catalogs.models.get(model_id)
        if existing is None:
            _reject(f"unknown coffee machine model {model_id}", "unknown_catalog_entry")
        normalized = _require_name(name)
        self._reject_duplicate_model(normalized, current_id=model_id)
        turning_floor_on = floor_standing and not existing.floor_standing
        if turning_floor_on and self._model_holds_stand(model_id):
            _reject(
                "floor standing is blocked while machines store a stand",
                "floor_standing_blocked_by_stand",
            )
        saved = CoffeeMachineModel(
            model_id=model_id,
            name=normalized,
            floor_standing=floor_standing,
        )
        self.catalogs.models.upsert(saved)
        self._audit(
            "save_coffee_machine_model",
            {"model_id": model_id, "name": normalized, "floor_standing": str(floor_standing)},
            actor_telegram_user_id,
        )
        return saved

    def delete_model(self, *, model_id: str, actor_telegram_user_id: int) -> None:
        if self.catalogs.models.get(model_id) is None:
            _reject(f"unknown coffee machine model {model_id}", "unknown_catalog_entry")
        if any(
            machine.coffee_machine_model_id == model_id
            for machine in self.stores.machines.list_all()
        ):
            _reject("catalog entry is in use", "catalog_entry_in_use")
        self.catalogs.models.delete(model_id)
        self._audit(
            "delete_coffee_machine_model",
            {"model_id": model_id},
            actor_telegram_user_id,
        )

    def create_stand_type(self, *, name: str, actor_telegram_user_id: int) -> StandType:
        normalized = _require_name(name)
        self._reject_duplicate_stand_type(normalized, current_id=None)
        stand_type_id = str(self.stores.counters.allocate_next(STAND_TYPE_COUNTER_KEY))
        stand_type = StandType(stand_type_id=stand_type_id, name=normalized)
        self.catalogs.stand_types.upsert(stand_type)
        self._audit(
            "create_stand_type",
            {"stand_type_id": stand_type_id, "name": normalized},
            actor_telegram_user_id,
        )
        return stand_type

    def save_stand_type(
        self,
        *,
        stand_type_id: str,
        name: str,
        actor_telegram_user_id: int,
    ) -> StandType:
        if self.catalogs.stand_types.get(stand_type_id) is None:
            _reject(f"unknown stand type {stand_type_id}", "unknown_catalog_entry")
        normalized = _require_name(name)
        self._reject_duplicate_stand_type(normalized, current_id=stand_type_id)
        saved = StandType(stand_type_id=stand_type_id, name=normalized)
        self.catalogs.stand_types.upsert(saved)
        self._audit(
            "save_stand_type",
            {"stand_type_id": stand_type_id, "name": normalized},
            actor_telegram_user_id,
        )
        return saved

    def delete_stand_type(self, *, stand_type_id: str, actor_telegram_user_id: int) -> None:
        if self.catalogs.stand_types.get(stand_type_id) is None:
            _reject(f"unknown stand type {stand_type_id}", "unknown_catalog_entry")
        if any(
            machine.stand_type_id == stand_type_id for machine in self.stores.machines.list_all()
        ):
            _reject("catalog entry is in use", "catalog_entry_in_use")
        self.catalogs.stand_types.delete(stand_type_id)
        self._audit(
            "delete_stand_type",
            {"stand_type_id": stand_type_id},
            actor_telegram_user_id,
        )

    def create_stand_color(self, *, name: str, actor_telegram_user_id: int) -> StandColor:
        normalized = _require_name(name)
        self._reject_duplicate_stand_color(normalized, current_id=None)
        stand_color_id = str(self.stores.counters.allocate_next(STAND_COLOR_COUNTER_KEY))
        stand_color = StandColor(stand_color_id=stand_color_id, name=normalized)
        self.catalogs.stand_colors.upsert(stand_color)
        self._audit(
            "create_stand_color",
            {"stand_color_id": stand_color_id, "name": normalized},
            actor_telegram_user_id,
        )
        return stand_color

    def save_stand_color(
        self,
        *,
        stand_color_id: str,
        name: str,
        actor_telegram_user_id: int,
    ) -> StandColor:
        if self.catalogs.stand_colors.get(stand_color_id) is None:
            _reject(f"unknown stand color {stand_color_id}", "unknown_catalog_entry")
        normalized = _require_name(name)
        self._reject_duplicate_stand_color(normalized, current_id=stand_color_id)
        saved = StandColor(stand_color_id=stand_color_id, name=normalized)
        self.catalogs.stand_colors.upsert(saved)
        self._audit(
            "save_stand_color",
            {"stand_color_id": stand_color_id, "name": normalized},
            actor_telegram_user_id,
        )
        return saved

    def delete_stand_color(self, *, stand_color_id: str, actor_telegram_user_id: int) -> None:
        if self.catalogs.stand_colors.get(stand_color_id) is None:
            _reject(f"unknown stand color {stand_color_id}", "unknown_catalog_entry")
        if any(
            machine.stand_color_id == stand_color_id for machine in self.stores.machines.list_all()
        ):
            _reject("catalog entry is in use", "catalog_entry_in_use")
        self.catalogs.stand_colors.delete(stand_color_id)
        self._audit(
            "delete_stand_color",
            {"stand_color_id": stand_color_id},
            actor_telegram_user_id,
        )

    def _reject_duplicate_model(self, name: str, *, current_id: str | None) -> None:
        for model in self.catalogs.models.list_all():
            if model.name == name and model.model_id != current_id:
                _reject("duplicate catalog name", "catalog_name_invalid")

    def _reject_duplicate_stand_type(self, name: str, *, current_id: str | None) -> None:
        for stand_type in self.catalogs.stand_types.list_all():
            if stand_type.name == name and stand_type.stand_type_id != current_id:
                _reject("duplicate catalog name", "catalog_name_invalid")

    def _reject_duplicate_stand_color(self, name: str, *, current_id: str | None) -> None:
        for stand_color in self.catalogs.stand_colors.list_all():
            if stand_color.name == name and stand_color.stand_color_id != current_id:
                _reject("duplicate catalog name", "catalog_name_invalid")

    def _model_holds_stand(self, model_id: str) -> bool:
        return any(
            machine.coffee_machine_model_id == model_id
            and (machine.stand_type_id is not None or machine.stand_color_id is not None)
            for machine in self.stores.machines.list_all()
        )

    def _audit(self, command: str, payload: dict[str, str], actor_telegram_user_id: int) -> None:
        self.stores.audit.append(
            MasterDataAuditRecord(
                at=self.now_factory(),
                actor_telegram_user_id=actor_telegram_user_id,
                command=command,
                payload=payload,
            )
        )
