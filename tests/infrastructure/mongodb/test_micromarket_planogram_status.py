from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.micromarket_loading import MicromarketPlanogram, MicromarketPlanogramLine
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.infrastructure.mongodb.micromarket_planograms import MongoMicromarketPlanogramStore


class _Collection:
    def __init__(self, document: dict[str, object] | None) -> None:
        self._document = document
        self.replaced: dict[str, object] | None = None

    def find_one(self, filter: dict[str, object]) -> dict[str, object] | None:
        del filter
        return self._document

    def find(self, filter: dict[str, object], **kwargs: object) -> list[dict[str, object]]:
        del filter, kwargs
        return [] if self._document is None else [self._document]

    def replace_one(
        self,
        filter: dict[str, object],
        replacement: dict[str, object],
        *,
        upsert: bool = False,
    ) -> None:
        del filter, upsert
        self.replaced = replacement


def test_planogram_document_without_group_loads_none() -> None:
    collection = _Collection(
        {
            "_id": "701",
            "updated_at": datetime(2026, 9, 25, tzinfo=UTC),
            "lines": [
                {
                    "product_code": "2311",
                    "target_qty": 1,
                    "price_rub": "10",
                    "active": True,
                    "sort_order": 0,
                },
            ],
        },
    )
    doc = MongoMicromarketPlanogramStore(collection=collection).get("701")
    assert doc is not None
    assert doc.lines[0].kit_group_id is None
    assert doc.lines[0].price_origin == "manual"
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert doc.shop_list_error == ""
    assert doc.shop_list_publication_id == ""


def test_planogram_line_price_origin_roundtrip() -> None:
    collection = _Collection(None)
    store = MongoMicromarketPlanogramStore(collection=collection)
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                    price_origin="calculated",
                ),
            ),
            updated_at=datetime(2026, 9, 25, tzinfo=UTC),
        ),
    )
    assert collection.replaced is not None
    assert collection.replaced["lines"][0]["price_origin"] == "calculated"
    collection._document = collection.replaced
    loaded = store.get("701")
    assert loaded is not None
    assert loaded.lines[0].price_origin == "calculated"


def test_planogram_upsert_writes_group_and_status() -> None:
    collection = _Collection(None)
    store = MongoMicromarketPlanogramStore(collection=collection)
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            updated_at=datetime(2026, 9, 25, tzinfo=UTC),
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_error="",
            shop_list_publication_id="pub-1",
        ),
    )
    assert collection.replaced is not None
    assert collection.replaced["lines"][0]["kit_group_id"] == 6348
    assert collection.replaced["shop_list_status"] == "published"
    assert collection.replaced["shop_list_publication_id"] == "pub-1"
