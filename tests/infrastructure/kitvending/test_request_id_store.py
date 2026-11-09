from __future__ import annotations

import threading

import pytest

import src.infrastructure.integrations.kitvending.request_id_store as store_module
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)


def test_in_memory_next_id_monotonic_per_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module.time, "time", lambda: 1_781_760_000.0)
    store = InMemoryKitVendingRequestIdStore()

    first = store.next_id(login="head")
    second = store.next_id(login="head")

    assert first == 1_781_760_000_000
    assert second == 1_781_760_000_001


def test_in_memory_next_id_logins_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module.time, "time", lambda: 1_781_760_000.0)
    store = InMemoryKitVendingRequestIdStore()

    head = store.next_id(login="head")
    child = store.next_id(login="child")

    assert head == 1_781_760_000_000
    assert child == 1_781_760_000_000


def test_in_memory_next_id_never_decreases_after_high_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryKitVendingRequestIdStore()
    store.bump_floor(login="head", floor=9_999_999_999_999)
    monkeypatch.setattr(store_module.time, "time", lambda: 1_781_760_000.0)

    assert store.next_id(login="head") == 10_000_000_000_000


def test_in_memory_bump_floor_raises_watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module.time, "time", lambda: 1_781_760_000.0)
    store = InMemoryKitVendingRequestIdStore()
    store.next_id(login="head")
    store.bump_floor(login="head", floor=9_000_000_000_000)

    assert store.next_id(login="head") == 9_000_000_000_001


def test_in_memory_concurrent_threads_monotonic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module.time, "time", lambda: 1_781_760_000.0)
    store = InMemoryKitVendingRequestIdStore()
    results: list[int] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        results.append(store.next_id(login="head"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 8
    assert len(set(results)) == 8
    assert min(results) == 1_781_760_000_000
    assert max(results) == 1_781_760_000_007
