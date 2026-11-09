from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.infrastructure.product_identity.mongo_procurement_mirror_store import (
    MongoProcurementMirrorStore,
)


def _mirror(
    *,
    catalog_code: str = "2311",
    supplier_id: str | None = "agent-1",
    supplier_name: str | None = "ООО Поставщик",
    last_buy_price: Decimal | None = Decimal("12.50"),
    supply_moment: datetime | None = None,
    synced_at: datetime | None = None,
    package_quantity: Decimal | None = Decimal("6"),
    supplier_product_name: str | None = "Салат у поставщика",
) -> ProcurementMirror:
    return ProcurementMirror(
        catalog_code=catalog_code,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        last_buy_price=last_buy_price,
        supply_moment=supply_moment or datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
        synced_at=synced_at or datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        package_quantity=package_quantity,
        supplier_product_name=supplier_product_name,
    )


def test_mongo_procurement_mirror_upsert_get_roundtrip() -> None:
    collection = mongomock.MongoClient().db.product_procurement_mirror
    store = MongoProcurementMirrorStore.from_collection(collection)
    row = _mirror()
    store.upsert(row)
    assert store.get("2311") == row


def test_mongo_procurement_mirror_empty_supply_none_fields() -> None:
    collection = mongomock.MongoClient().db.product_procurement_mirror
    store = MongoProcurementMirrorStore.from_collection(collection)
    empty = ProcurementMirror(
        catalog_code="2311",
        supplier_id=None,
        supplier_name=None,
        last_buy_price=None,
        supply_moment=None,
        synced_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )
    store.upsert(empty)
    loaded = store.get("2311")
    assert loaded is not None
    assert loaded.supplier_id is None
    assert loaded.supplier_name is None
    assert loaded.last_buy_price is None
    assert loaded.supply_moment is None
    document = collection.find_one({"_id": "2311"})
    assert document is not None
    assert document["supplier_id"] is None
    assert document["supplier_name"] is None
    assert document["last_buy_price"] is None
    assert document["supply_moment"] is None


def test_mongo_procurement_mirror_codes() -> None:
    collection = mongomock.MongoClient().db.product_procurement_mirror
    store = MongoProcurementMirrorStore.from_collection(collection)
    store.upsert(_mirror(catalog_code="2311"))
    store.upsert(_mirror(catalog_code="2312", last_buy_price=Decimal("1.00")))
    assert set(store.codes()) == {"2311", "2312"}
    store.delete("2311")
    assert store.get("2311") is None
    assert store.codes() == ("2312",)


def test_mongo_procurement_mirror_price_stored_as_decimal_string() -> None:
    collection = mongomock.MongoClient().db.product_procurement_mirror
    store = MongoProcurementMirrorStore.from_collection(collection)
    store.upsert(_mirror(last_buy_price=Decimal("12.50")))
    updated = _mirror(last_buy_price=Decimal("15.00"), supplier_name="Другой")
    store.upsert(updated)
    assert store.get("2311") == updated
    document = collection.find_one({"_id": "2311"})
    assert document is not None
    assert document["last_buy_price"] == "15.00"
    assert isinstance(document["last_buy_price"], str)
