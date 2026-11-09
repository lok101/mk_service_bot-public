from __future__ import annotations

from src.application.master_data import InMemoryMasterDataStores, MachineKind, allocate_machine_id


def test_allocate_micro_market_floor_701() -> None:
    stores = InMemoryMasterDataStores()
    mid = allocate_machine_id(stores.counters, MachineKind.MICRO_MARKET)
    assert mid.value == "701"
    assert allocate_machine_id(stores.counters, MachineKind.MICRO_MARKET).value == "702"


def test_machine_kind_micro_market_value() -> None:
    assert MachineKind.MICRO_MARKET.value == "micro_market"
