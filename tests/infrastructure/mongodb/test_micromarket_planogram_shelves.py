from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.micromarket_loading import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
)
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
        self._document = replacement


_FROZEN = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _line(
    *,
    code: str = "2311",
    group: int | None = 10,
    order: int = 0,
) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code=code,
        target_qty=1,
        price_rub=Decimal("10"),
        active=True,
        sort_order=order,
        kit_group_id=group,
    )


def test_planogram_upsert_writes_shelves_and_roundtrips() -> None:
    collection = _Collection(None)
    store = MongoMicromarketPlanogramStore(collection=collection)
    shelves = (
        MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
        MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
    )
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(group=10, order=0), _line(code="2312", group=20, order=1)),
            updated_at=_FROZEN,
            shelves=shelves,
        ),
    )
    assert collection.replaced is not None
    assert collection.replaced["shelves"] == [
        {"kit_group_id": 10, "sort_order": 0},
        {"kit_group_id": 20, "sort_order": 1},
    ]
    loaded = store.get("701")
    assert loaded is not None
    assert loaded.shelves == shelves


def test_planogram_upsert_writes_empty_shelves_tuple() -> None:
    collection = _Collection(None)
    store = MongoMicromarketPlanogramStore(collection=collection)
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(),
            updated_at=_FROZEN,
            shelves=(),
        ),
    )
    assert collection.replaced is not None
    assert collection.replaced["shelves"] == []
    loaded = store.get("701")
    assert loaded is not None
    assert loaded.shelves == ()


def test_planogram_upsert_omits_shelves_key_when_none() -> None:
    collection = _Collection(None)
    store = MongoMicromarketPlanogramStore(collection=collection)
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line(),),
            updated_at=_FROZEN,
            shelves=None,
        ),
    )
    assert collection.replaced is not None
    assert "shelves" not in collection.replaced


def test_planogram_document_without_shelves_key_loads_none() -> None:
    collection = _Collection(
        {
            "_id": "701",
            "updated_at": _FROZEN,
            "lines": [
                {
                    "product_code": "2311",
                    "target_qty": 1,
                    "price_rub": "10",
                    "active": True,
                    "sort_order": 0,
                    "kit_group_id": 10,
                },
            ],
        },
    )
    doc = MongoMicromarketPlanogramStore(collection=collection).get("701")
    assert doc is not None
    assert doc.shelves is None


def test_planogram_document_rejects_non_int_shelf_id() -> None:
    collection = _Collection(
        {
            "_id": "701",
            "updated_at": _FROZEN,
            "lines": [],
            "shelves": [{"kit_group_id": "10", "sort_order": 0}],
        },
    )
    with pytest.raises(ValueError, match="kit_group_id"):
        MongoMicromarketPlanogramStore(collection=collection).get("701")


def test_planogram_document_rejects_duplicate_shelf_id() -> None:
    collection = _Collection(
        {
            "_id": "701",
            "updated_at": _FROZEN,
            "lines": [],
            "shelves": [
                {"kit_group_id": 10, "sort_order": 0},
                {"kit_group_id": 10, "sort_order": 1},
            ],
        },
    )
    with pytest.raises(ValueError, match="duplicate"):
        MongoMicromarketPlanogramStore(collection=collection).get("701")
