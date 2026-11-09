from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.application.master_data import (
    MachineKind,
    MachineStatus,
    MasterLocation,
    MasterMachine,
    MasterPlacement,
)
from src.domain.ids import MachineId
from src.infrastructure.mongodb.master_data import MongoMasterDataStores

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_mongo_master_data_roundtrip() -> None:
    client = mongomock.MongoClient()
    stores = MongoMasterDataStores.from_database(
        client.db,
        locations_collection="master_locations",
        machines_collection="master_machines",
        placements_collection="master_placements",
        counters_collection="master_data_counters",
        audit_collection="master_data_audit",
    )
    stores.locations.upsert(
        MasterLocation(
            location_id="1",
            name="A",
            city="Город",
            street="x",
            house="1",
            display_name="A | x, 1",
            latitude=Decimal("1.5"),
            longitude=Decimal("2.5"),
        )
    )
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p1",
            machine_id=MachineId("101"),
            location_id="1",
            valid_from=_NOW,
            valid_to=None,
        )
    )
    assert stores.locations.get("1") is not None
    assert stores.machines.get(MachineId("101")) is not None
    assert stores.placements.get_open(MachineId("101")) is not None


def test_allocate_next_sequential_unique() -> None:
    client = mongomock.MongoClient()
    stores = MongoMasterDataStores.from_database(
        client.db,
        locations_collection="master_locations",
        machines_collection="master_machines",
        placements_collection="master_placements",
        counters_collection="master_data_counters",
        audit_collection="master_data_audit",
    )
    assert stores.counters.allocate_next("machine") == 1
    assert stores.counters.allocate_next("machine") == 2
    assert stores.counters.allocate_next("machine") == 3
    assert stores.counters.get("machine") == 3


def test_master_data_ensure_indexes_creates_placement_and_user_indexes() -> None:
    client = mongomock.MongoClient()
    stores = MongoMasterDataStores.from_database(
        client.db,
        locations_collection="master_locations",
        machines_collection="master_machines",
        placements_collection="master_placements",
        counters_collection="master_data_counters",
        audit_collection="master_data_audit",
    )
    assert "machine_id_valid_to" in stores.placements.collection.index_information()

    from src.infrastructure.mongodb.system_users import MongoSystemUserStore

    user_store = MongoSystemUserStore(
        users_collection=client.db["master_system_users"],
        audit_collection=client.db["master_system_users_audit"],
    )
    user_store.ensure_indexes()
    assert "user_is_active" in user_store.users_collection.index_information()


def test_location_codec_roundtrip_parts() -> None:
    client = mongomock.MongoClient()
    stores = MongoMasterDataStores.from_database(
        client.db,
        locations_collection="master_locations",
        machines_collection="master_machines",
        placements_collection="master_placements",
        counters_collection="master_data_counters",
        audit_collection="master_data_audit",
    )
    loc = MasterLocation(
        location_id="10",
        name="МЦ",
        city="Казань",
        street="Фучика",
        house="3",
        display_name="МЦ | Фучика, 3",
        latitude=None,
        longitude=None,
    )
    stores.locations.upsert(loc)
    loaded = stores.locations.get("10")
    assert loaded == loc


def test_location_codec_legacy_empty_parts() -> None:
    client = mongomock.MongoClient()
    stores = MongoMasterDataStores.from_database(
        client.db,
        locations_collection="master_locations",
        machines_collection="master_machines",
        placements_collection="master_placements",
        counters_collection="master_data_counters",
        audit_collection="master_data_audit",
    )
    stores.locations.collection.replace_one(
        {"_id": "9"},
        {"_id": "9", "display_name": "МЦ Здоровая семья | Фучика, 3", "address": "old"},
        upsert=True,
    )
    loaded = stores.locations.get("9")
    assert loaded is not None
    assert loaded.name == ""
    assert loaded.city == ""
    assert loaded.street == ""
    assert loaded.house == ""
    assert loaded.display_name == "МЦ Здоровая семья | Фучика, 3"
