from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.application.master_data import (
    CoffeeEquipmentCatalogs,
    CoffeeEquipmentCommands,
    InMemoryCoffeeMachineModelStore,
    InMemoryMasterDataStores,
    InMemoryStandColorStore,
    InMemoryStandTypeStore,
    MachineKind,
    MachineStatus,
    MasterDataCommandRejected,
    MasterMachine,
    UpdateMachineSettings,
    UpdateMachineSettingsInput,
)
from src.domain.ids import MachineId

_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_ACTOR = 1001


def _catalogs() -> CoffeeEquipmentCatalogs:
    return CoffeeEquipmentCatalogs(
        models=InMemoryCoffeeMachineModelStore(),
        stand_types=InMemoryStandTypeStore(),
        stand_colors=InMemoryStandColorStore(),
    )


def _commands(
    stores: InMemoryMasterDataStores,
    catalogs: CoffeeEquipmentCatalogs,
) -> CoffeeEquipmentCommands:
    return CoffeeEquipmentCommands(
        stores=stores,
        catalogs=catalogs,
        now_factory=lambda: _NOW,
    )


def _machine(kind: MachineKind, machine_id: str = "101") -> MasterMachine:
    return MasterMachine(
        machine_id=MachineId(machine_id),
        kind=kind,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
    )


def _save_card(
    stores: InMemoryMasterDataStores,
    catalogs: CoffeeEquipmentCatalogs,
    machine: MasterMachine,
    *,
    model_id: str | None,
    stand_type_id: str | None = None,
    stand_color_id: str | None = None,
) -> None:
    UpdateMachineSettings(
        stores=stores,
        now_factory=lambda: _NOW,
        catalogs=catalogs,
    ).execute(
        UpdateMachineSettingsInput(
            machine_id=machine.machine_id,
            include_in_no_sales_monitoring=True,
            create_visit_on_no_sales=True,
            include_in_visit_photo_review=True,
            actor_telegram_user_id=_ACTOR,
            coffee_machine_model_id=model_id,
            stand_type_id=stand_type_id,
            stand_color_id=stand_color_id,
            apply_equipment_catalogs=True,
        )
    )


def test_create_catalogs_and_assign_them_to_coffee() -> None:
    stores = InMemoryMasterDataStores()
    catalogs = _catalogs()
    commands = _commands(stores, catalogs)
    model = commands.create_model(
        name="  Jetinno  ",
        floor_standing=False,
        actor_telegram_user_id=_ACTOR,
    )
    stand_type = commands.create_stand_type(name="Новый образец", actor_telegram_user_id=_ACTOR)
    stand_color = commands.create_stand_color(name="Чёрный", actor_telegram_user_id=_ACTOR)
    machine = _machine(MachineKind.COFFEE)
    stores.machines.upsert(machine)

    _save_card(
        stores,
        catalogs,
        machine,
        model_id=model.model_id,
        stand_type_id=stand_type.stand_type_id,
        stand_color_id=stand_color.stand_color_id,
    )

    saved = stores.machines.get(machine.machine_id)
    assert saved is not None
    assert model.name == "Jetinno"
    assert saved.coffee_machine_model_id == model.model_id
    assert saved.stand_type_id == stand_type.stand_type_id
    assert saved.stand_color_id == stand_color.stand_color_id
    assert stores.audit.list_all()[-1].command == "update_machine_settings"


def test_rename_keeps_card_id_and_deleted_id_is_not_reused() -> None:
    stores = InMemoryMasterDataStores()
    catalogs = _catalogs()
    commands = _commands(stores, catalogs)
    model = commands.create_model(name="JL", floor_standing=False, actor_telegram_user_id=_ACTOR)
    machine = _machine(MachineKind.COFFEE)
    stores.machines.upsert(machine)
    _save_card(stores, catalogs, machine, model_id=model.model_id)
    commands.save_model(
        model_id=model.model_id,
        name="JL 300",
        floor_standing=False,
        actor_telegram_user_id=_ACTOR,
    )
    saved = stores.machines.get(machine.machine_id)
    renamed = catalogs.models.get(model.model_id)
    assert saved is not None
    assert renamed is not None
    assert saved.coffee_machine_model_id == model.model_id
    assert renamed.name == "JL 300"

    stores.machines.upsert(replace(saved, coffee_machine_model_id=None))
    commands.delete_model(model_id=model.model_id, actor_telegram_user_id=_ACTOR)
    nxt = commands.create_model(name="Другая", floor_standing=False, actor_telegram_user_id=_ACTOR)
    assert nxt.model_id != model.model_id


def test_floor_model_clears_stand_in_the_same_save() -> None:
    stores = InMemoryMasterDataStores()
    catalogs = _catalogs()
    commands = _commands(stores, catalogs)
    model = commands.create_model(
        name="Напольная",
        floor_standing=True,
        actor_telegram_user_id=_ACTOR,
    )
    stand_type = commands.create_stand_type(name="Старый", actor_telegram_user_id=_ACTOR)
    stand_color = commands.create_stand_color(name="Белый", actor_telegram_user_id=_ACTOR)
    machine = _machine(MachineKind.COFFEE)
    stores.machines.upsert(machine)

    _save_card(
        stores,
        catalogs,
        machine,
        model_id=model.model_id,
        stand_type_id=stand_type.stand_type_id,
        stand_color_id=stand_color.stand_color_id,
    )

    saved = stores.machines.get(machine.machine_id)
    assert saved is not None
    assert saved.coffee_machine_model_id == model.model_id
    assert saved.stand_type_id is None
    assert saved.stand_color_id is None


def test_non_floor_model_may_omit_stand_and_old_machine_has_empty_refs() -> None:
    stores = InMemoryMasterDataStores()
    catalogs = _catalogs()
    commands = _commands(stores, catalogs)
    model = commands.create_model(
        name="Настольная",
        floor_standing=False,
        actor_telegram_user_id=_ACTOR,
    )
    machine = _machine(MachineKind.COFFEE)
    assert machine.coffee_machine_model_id is None
    assert machine.stand_type_id is None
    assert machine.stand_color_id is None
    assert machine.include_in_visit_photo_review is True
    stores.machines.upsert(machine)
    _save_card(stores, catalogs, machine, model_id=model.model_id)
    saved = stores.machines.get(machine.machine_id)
    assert saved is not None
    assert saved.stand_type_id is None
    assert saved.stand_color_id is None


def test_catalog_errors_do_not_change_the_card() -> None:
    stores = InMemoryMasterDataStores()
    catalogs = _catalogs()
    commands = _commands(stores, catalogs)
    model = commands.create_model(name="JL", floor_standing=False, actor_telegram_user_id=_ACTOR)
    stand_type = commands.create_stand_type(name="Новый", actor_telegram_user_id=_ACTOR)
    stand_color = commands.create_stand_color(name="Серый", actor_telegram_user_id=_ACTOR)
    machine = _machine(MachineKind.COFFEE)
    stores.machines.upsert(machine)
    _save_card(
        stores,
        catalogs,
        machine,
        model_id=model.model_id,
        stand_type_id=stand_type.stand_type_id,
        stand_color_id=stand_color.stand_color_id,
    )

    with pytest.raises(MasterDataCommandRejected) as empty_name:
        commands.create_model(name="  ", floor_standing=False, actor_telegram_user_id=_ACTOR)
    assert empty_name.value.code == "catalog_name_invalid"

    with pytest.raises(MasterDataCommandRejected) as duplicate:
        commands.create_stand_type(name="Новый", actor_telegram_user_id=_ACTOR)
    assert duplicate.value.code == "catalog_name_invalid"

    with pytest.raises(MasterDataCommandRejected) as stand_only:
        _save_card(
            stores,
            catalogs,
            machine,
            model_id=None,
            stand_type_id=stand_type.stand_type_id,
        )
    assert stand_only.value.code == "stand_not_allowed"

    with pytest.raises(MasterDataCommandRejected) as unknown:
        _save_card(stores, catalogs, machine, model_id="missing")
    assert unknown.value.code == "unknown_catalog_entry"

    with pytest.raises(MasterDataCommandRejected) as in_use:
        commands.delete_model(model_id=model.model_id, actor_telegram_user_id=_ACTOR)
    assert in_use.value.code == "catalog_entry_in_use"

    with pytest.raises(MasterDataCommandRejected) as floor_blocked:
        commands.save_model(
            model_id=model.model_id,
            name="JL",
            floor_standing=True,
            actor_telegram_user_id=_ACTOR,
        )
    assert floor_blocked.value.code == "floor_standing_blocked_by_stand"

    saved = stores.machines.get(machine.machine_id)
    assert saved is not None
    assert saved.coffee_machine_model_id == model.model_id
    assert saved.stand_type_id == stand_type.stand_type_id
    assert saved.stand_color_id == stand_color.stand_color_id
    kept = catalogs.models.get(model.model_id)
    assert kept is not None
    assert kept.floor_standing is False


@pytest.mark.parametrize("kind", [MachineKind.SNACK, MachineKind.MICRO_MARKET])
def test_non_coffee_rejects_catalog_refs(kind: MachineKind) -> None:
    stores = InMemoryMasterDataStores()
    catalogs = _catalogs()
    commands = _commands(stores, catalogs)
    model = commands.create_model(name="JL", floor_standing=False, actor_telegram_user_id=_ACTOR)
    machine = _machine(kind, machine_id="501" if kind is MachineKind.SNACK else "701")
    stores.machines.upsert(machine)
    with pytest.raises(MasterDataCommandRejected) as rejected:
        _save_card(stores, catalogs, machine, model_id=model.model_id)
    assert rejected.value.code == "equipment_catalog_not_for_kind"
    saved = stores.machines.get(machine.machine_id)
    assert saved is not None
    assert saved.coffee_machine_model_id is None
