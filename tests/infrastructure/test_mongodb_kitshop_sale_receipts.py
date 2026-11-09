from __future__ import annotations

import mongomock
import pytest

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.kitshop_sale_receipts import MongoKitShopSaleReceiptStore


def test_mongo_receipt_save_is_idempotent_on_sale_id() -> None:
    # happy + idempotency
    collection = mongomock.MongoClient().db.kitshop_sale_receipts
    store = MongoKitShopSaleReceiptStore(collection=collection)
    first = {"SaleId": 100, "marker": "first"}
    second = {"SaleId": 100, "marker": "second"}
    store.save_if_absent(sale_id=100, payload=first)
    store.save_if_absent(sale_id=100, payload=second)
    assert store.load(100) == first


def test_mongo_receipt_load_missing_is_none() -> None:
    # edge
    collection = mongomock.MongoClient().db.kitshop_sale_receipts
    store = MongoKitShopSaleReceiptStore(collection=collection)
    assert store.load(100) is None


def test_mongo_receipt_from_settings_uses_collection_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: имя коллекции из Settings; mongomock не проходит beartype как pymongo.MongoClient
    collection = mongomock.MongoClient().db.kitshop_sale_receipts
    captured: dict[str, str] = {}

    def _resolve(
        settings: MongoSettings,
        *,
        collection_name: str,
        owner: str,
        client: object,
    ) -> object:
        del settings, client
        captured["collection_name"] = collection_name
        captured["owner"] = owner
        return collection

    monkeypatch.setattr(
        "src.infrastructure.mongodb.kitshop_sale_receipts.resolve_collection",
        _resolve,
    )
    settings = MongoSettings.model_construct(
        uri="mongodb://localhost:27017",
        database="mk_service_bot",
        kitshop_sale_receipts_collection="kitshop_sale_receipts",
    )
    store = MongoKitShopSaleReceiptStore.from_settings(settings, client=None)
    assert captured["collection_name"] == "kitshop_sale_receipts"
    assert captured["owner"] == "MongoKitShopSaleReceiptStore"
    store.save_if_absent(sale_id=7, payload={"SaleId": 7})
    assert store.load(7) == {"SaleId": 7}
