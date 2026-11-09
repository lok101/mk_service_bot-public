from __future__ import annotations

import threading

import pytest

from src.application.master_data import InMemoryMasterDataStores
from src.application.master_data.models import (
    LocationIdOverflow,
    MachineKind,
    allocate_location_id,
    allocate_machine_id,
)


def test_allocate_coffee_starts_at_101() -> None:
    stores = InMemoryMasterDataStores()
    mid = allocate_machine_id(stores.counters, MachineKind.COFFEE)
    assert mid.value == "101"
    assert allocate_machine_id(stores.counters, MachineKind.COFFEE).value == "102"


def test_allocate_snack_starts_at_501() -> None:
    stores = InMemoryMasterDataStores()
    mid = allocate_machine_id(stores.counters, MachineKind.SNACK)
    assert mid.value == "501"


def test_allocate_location_overflow_raises() -> None:
    stores = InMemoryMasterDataStores()
    stores.counters.set("location", 999_999)
    with pytest.raises(LocationIdOverflow):
        allocate_location_id(stores.counters)


def test_allocate_machine_id_parallel_unique() -> None:
    stores = InMemoryMasterDataStores()
    results: list[str] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def _worker() -> None:
        barrier.wait()
        mid = allocate_machine_id(stores.counters, MachineKind.COFFEE)
        with results_lock:
            results.append(mid.value)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert len(results) == 8
    assert len(set(results)) == 8
