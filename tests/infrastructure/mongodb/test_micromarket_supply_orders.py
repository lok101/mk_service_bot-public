from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.domain.micromarket_loading.supply_order import (
    MicromarketSupplyOrder,
    MicromarketSupplyOrderLine,
    MicromarketSupplyOrderMachine,
)
from src.infrastructure.mongodb.micromarket_supply_orders import (
    MongoMicromarketSupplyOrderStore,
)


def _order(
    *,
    category: int = 2,
    package_quantity: Decimal | None = Decimal("6"),
    supplier_product_name: str | None = "Салат у поставщика",
    gap_qty: Decimal = Decimal("3"),
    forecast_qty: Decimal = Decimal("0"),
    need_qty: Decimal | None = None,
) -> MicromarketSupplyOrder:
    resolved_need = need_qty if need_qty is not None else gap_qty + forecast_qty
    return MicromarketSupplyOrder(
        order_id="ord-1",
        created_at=datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
        expected_arrival_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
        machines=(
            MicromarketSupplyOrderMachine(
                machine_id="mm-1",
                lines=(
                    MicromarketSupplyOrderLine(
                        product_code="2311",
                        need_qty=resolved_need,
                        category=category,  # type: ignore[arg-type]
                        name="Салат",
                        supplier_name="ООО Поставщик",
                        last_buy_price=Decimal("12.50"),
                        package_quantity=package_quantity,
                        supplier_product_name=supplier_product_name,
                        gap_qty=gap_qty,
                        forecast_qty=forecast_qty,
                    ),
                ),
            ),
        ),
    )


def test_mongo_supply_order_roundtrip_keeps_procurement_line_fields() -> None:
    collection = mongomock.MongoClient().db.micromarket_supply_orders
    store = MongoMicromarketSupplyOrderStore(collection=collection)
    order = _order(category=3, gap_qty=Decimal("3"), forecast_qty=Decimal("4"))
    store.save(order)
    loaded = store.get("ord-1")
    assert loaded is not None
    line = loaded.machines[0].lines[0]
    assert line.category == 3
    assert line.gap_qty == Decimal("3")
    assert line.forecast_qty == Decimal("4")
    assert line.need_qty == Decimal("7")
    assert line.package_quantity == Decimal("6")
    assert line.supplier_product_name == "Салат у поставщика"
    assert line.last_buy_price == Decimal("12.50")
    document = collection.find_one({"_id": "ord-1"})
    assert document is not None
    raw_line = document["machines"][0]["lines"][0]
    assert raw_line["category"] == 3
    assert raw_line["gap_qty"] == "3"
    assert raw_line["forecast_qty"] == "4"
    assert raw_line["package_quantity"] == "6"
    assert raw_line["supplier_product_name"] == "Салат у поставщика"
    assert isinstance(raw_line["package_quantity"], str)


def test_mongo_supply_order_legacy_line_without_gap_qty_derives_from_need_minus_forecast() -> None:
    collection = mongomock.MongoClient().db.micromarket_supply_orders
    store = MongoMicromarketSupplyOrderStore(collection=collection)
    collection.replace_one(
        {"_id": "ord-legacy-gap"},
        {
            "_id": "ord-legacy-gap",
            "created_at": datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
            "expected_arrival_at": datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
            "machines": [
                {
                    "machine_id": "mm-1",
                    "lines": [
                        {
                            "product_code": "2311",
                            "need_qty": "7",
                            "forecast_qty": "4",
                            "category": 2,
                            "name": "Салат",
                        },
                    ],
                },
            ],
        },
        upsert=True,
    )
    loaded = store.get("ord-legacy-gap")
    assert loaded is not None
    line = loaded.machines[0].lines[0]
    assert line.gap_qty == Decimal("3")
    assert line.forecast_qty == Decimal("4")
    assert line.need_qty == Decimal("7")


def test_mongo_supply_order_legacy_line_without_category_defaults_to_2() -> None:
    collection = mongomock.MongoClient().db.micromarket_supply_orders
    store = MongoMicromarketSupplyOrderStore(collection=collection)
    collection.replace_one(
        {"_id": "ord-legacy"},
        {
            "_id": "ord-legacy",
            "created_at": datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
            "machines": [
                {
                    "machine_id": "mm-1",
                    "lines": [
                        {
                            "product_code": "2311",
                            "need_qty": "3",
                            "name": "Салат",
                            "supplier_name": "ООО Поставщик",
                            "last_buy_price": "12.50",
                        },
                    ],
                },
            ],
        },
        upsert=True,
    )
    loaded = store.get("ord-legacy")
    assert loaded is not None
    assert loaded.machines[0].lines[0].category == 2


def test_mongo_supply_order_legacy_line_without_procurement_fields() -> None:
    collection = mongomock.MongoClient().db.micromarket_supply_orders
    store = MongoMicromarketSupplyOrderStore(collection=collection)
    collection.replace_one(
        {"_id": "ord-legacy-proc"},
        {
            "_id": "ord-legacy-proc",
            "created_at": datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
            "machines": [
                {
                    "machine_id": "mm-1",
                    "lines": [
                        {
                            "product_code": "2311",
                            "need_qty": "3",
                            "category": 2,
                            "name": "Салат",
                            "supplier_name": "ООО Поставщик",
                            "last_buy_price": "12.50",
                        },
                    ],
                },
            ],
        },
        upsert=True,
    )
    loaded = store.get("ord-legacy-proc")
    assert loaded is not None
    line = loaded.machines[0].lines[0]
    assert line.category == 2
    assert line.package_quantity is None
    assert line.supplier_product_name is None
