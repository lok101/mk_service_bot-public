from __future__ import annotations

import threading

import mongomock
import pytest

import src.infrastructure.mongodb.kitvending_request_ids as mongo_store_module
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.kitvending_request_ids import MongoKitVendingRequestIdStore


def _store(client: mongomock.MongoClient) -> MongoKitVendingRequestIdStore:
    collection = client["test"]["kitvending_request_ids"]
    return MongoKitVendingRequestIdStore.from_collection(collection)


def test_mongo_next_id_monotonic_per_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mongo_store_module.time, "time", lambda: 1_781_760_000.0)
    client = mongomock.MongoClient()
    store = _store(client)

    first = store.next_id(login="head")
    second = store.next_id(login="head")

    assert first == 1_781_760_000_000
    assert second == 1_781_760_000_001


def test_mongo_two_stores_share_watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mongo_store_module.time, "time", lambda: 1_781_760_000.0)
    client = mongomock.MongoClient()
    store_a = _store(client)
    store_b = _store(client)

    first = store_a.next_id(login="head")
    second = store_b.next_id(login="head")

    assert first == 1_781_760_000_000
    assert second == 1_781_760_000_001


def test_mongo_bump_floor_raises_watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mongo_store_module.time, "time", lambda: 1_781_760_000.0)
    client = mongomock.MongoClient()
    store = _store(client)
    store.next_id(login="head")
    store.bump_floor(login="head", floor=9_000_000_000_000)

    assert store.next_id(login="head") == 9_000_000_000_001


def test_mongo_bump_floor_concurrent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mongo_store_module.time, "time", lambda: 1_781_760_000.0)
    client = mongomock.MongoClient()
    store = _store(client)
    barrier = threading.Barrier(4)

    def worker(floor: int) -> None:
        barrier.wait()
        store.bump_floor(login="head", floor=floor)

    threads = [
        threading.Thread(target=worker, args=(9_000_000_000_000,)),
        threading.Thread(target=worker, args=(9_000_000_000_001,)),
        threading.Thread(target=worker, args=(8_000_000_000_000,)),
        threading.Thread(target=worker, args=(9_000_000_000_002,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    doc = client["test"]["kitvending_request_ids"].find_one({"_id": "head"})
    assert doc is not None
    assert doc["last_request_id"] == 9_000_000_000_002


def test_mongo_from_settings_resolves_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    client = mongomock.MongoClient()
    collection = client["test"]["kitvending_request_ids"]
    monkeypatch.setattr(
        mongo_store_module,
        "resolve_collection",
        lambda *args, **kwargs: collection,
    )
    monkeypatch.setattr(mongo_store_module.time, "time", lambda: 1_781_760_000.0)
    settings = MongoSettings.model_construct(uri="mongodb://test", database="test")

    store = MongoKitVendingRequestIdStore.from_settings(settings, client=client)

    assert store.next_id(login="head") == 1_781_760_000_000
    doc = collection.find_one({"_id": "head"})
    assert doc is not None
    assert doc["last_request_id"] == 1_781_760_000_000


def test_mongo_from_collection_accepts_mongomock() -> None:
    collection = mongomock.MongoClient()["test"]["kitvending_request_ids"]
    store = MongoKitVendingRequestIdStore.from_collection(collection)
    assert store.next_id(login="head") >= 1


def test_mongo_next_id_logins_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mongo_store_module.time, "time", lambda: 1_781_760_000.0)
    client = mongomock.MongoClient()
    store = _store(client)

    head = store.next_id(login="head")
    child = store.next_id(login="child")

    assert head == 1_781_760_000_000
    assert child == 1_781_760_000_000
