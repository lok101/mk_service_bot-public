from __future__ import annotations

from src.application.master_data import InMemoryMasterDataCounterStore, allocate_system_user_id


def test_allocate_system_user_id() -> None:
    counters = InMemoryMasterDataCounterStore()
    first = allocate_system_user_id(counters)
    second = allocate_system_user_id(counters)
    assert first == "1"
    assert second == "2"
