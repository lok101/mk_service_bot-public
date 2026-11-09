from __future__ import annotations

from decimal import Decimal

from mongomock import MongoClient

from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.matrix_sku_catalog import MongoMatrixSkuCatalogStore


def test_mongo_sku_catalog_round_trip() -> None:
    client: MongoClient = MongoClient()
    settings = MongoSettings(uri="mongodb://localhost", database="t")
    store = MongoMatrixSkuCatalogStore.from_settings(settings, client=client)
    entry = MatrixSkuCatalogEntry(
        product_code="SKU-9",
        display_name="Bar",
        capacity=7,
        product_multiplier=Decimal("1.5"),
    )
    store.upsert(entry)
    assert store.get("SKU-9") == entry
    assert store.list_all() == (entry,)
