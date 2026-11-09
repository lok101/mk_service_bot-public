from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.micromarket_loading import MicromarketPlanogram, MicromarketPlanogramLine
from src.infrastructure.mongodb.micromarket_planograms import MongoMicromarketPlanogramStore
from src.infrastructure.mongodb.snack_machine_layouts import MongoSnackMachineLayoutStore


class _Collection:
    def __init__(self, document: dict[str, Any] | None) -> None:
        self._document = document
        self.replaced: dict[str, Any] | None = None

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None:
        del filter
        return self._document

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> None:
        del filter, upsert
        self.replaced = replacement

    def find(self, filter: dict[str, Any]) -> list[dict[str, Any]]:
        del filter
        if self._document is None:
            return []
        return [self._document]

    def count_documents(self, filter: dict[str, Any]) -> int:
        del filter
        return 0 if self._document is None else 1


def test_planogram_line_domain_product_id_defaults_empty() -> None:
    line = MicromarketPlanogramLine(
        product_code="2311",
        target_qty=1,
        price_rub=Decimal("10"),
        active=True,
        sort_order=0,
    )
    assert line.domain_product_id is None


def test_snack_cell_domain_product_id_defaults_empty() -> None:
    cell = SnackMachineLayoutCell(line_number=1, product_code="2311")
    assert cell.domain_product_id is None


def test_old_micromarket_line_without_domain_product_id_reads_empty() -> None:
    collection = _Collection(
        {
            "_id": "701",
            "updated_at": datetime(2026, 9, 28, tzinfo=UTC),
            "lines": [
                {
                    "product_code": "2311",
                    "target_qty": 1,
                    "price_rub": "10",
                    "active": True,
                    "sort_order": 0,
                    "kit_group_id": 6348,
                }
            ],
            "shop_list_status": "unpublished",
            "shop_list_error": "",
            "shop_list_publication_id": "",
        }
    )
    doc = MongoMicromarketPlanogramStore(collection=collection).get("701")
    assert doc is not None
    assert doc.lines[0].domain_product_id is None
    assert doc.lines[0].product_code == "2311"


def test_micromarket_line_roundtrip_persists_domain_product_id() -> None:
    collection = _Collection(None)
    store = MongoMicromarketPlanogramStore(collection=collection)
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                    domain_product_id="prod-1",
                ),
            ),
            updated_at=datetime(2026, 9, 28, tzinfo=UTC),
        )
    )
    assert collection.replaced is not None
    assert collection.replaced["lines"][0]["domain_product_id"] == "prod-1"


def test_old_snack_cell_without_domain_product_id_reads_empty() -> None:
    collection = _Collection(
        {
            "_id": "514",
            "logical_matrix_name": "514",
            "matrix_multiplier": "1",
            "auto_sync_enabled": False,
            "cells": [{"line_number": 1, "product_code": "2311"}],
            "shelf_count": 6,
            "slots_per_shelf": 10,
            "merges": [],
        }
    )
    layout = MongoSnackMachineLayoutStore(collection=collection).get("514")
    assert layout is not None
    assert layout.cells[0].domain_product_id is None
    assert layout.cells[0].product_code == "2311"


def test_snack_cell_roundtrip_persists_domain_product_id() -> None:
    collection = _Collection(None)
    store = MongoSnackMachineLayoutStore(collection=collection)
    store.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="514",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(
                SnackMachineLayoutCell(
                    line_number=1,
                    product_code=None,
                    domain_product_id="prod-1",
                ),
            ),
        )
    )
    assert collection.replaced is not None
    assert collection.replaced["cells"][0]["domain_product_id"] == "prod-1"


def test_old_micromarket_line_without_pending_exit_reads_false() -> None:
    collection = _Collection(
        {
            "_id": "701",
            "updated_at": datetime(2026, 9, 28, tzinfo=UTC),
            "lines": [
                {
                    "product_code": "2311",
                    "target_qty": 1,
                    "price_rub": "10",
                    "active": True,
                    "sort_order": 0,
                    "kit_group_id": 6348,
                }
            ],
            "shop_list_status": "unpublished",
            "shop_list_error": "",
            "shop_list_publication_id": "",
        }
    )
    doc = MongoMicromarketPlanogramStore(collection=collection).get("701")
    assert doc is not None
    assert doc.lines[0].pending_exit is False


def test_micromarket_line_pending_exit_roundtrip() -> None:
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
                    pending_exit=True,
                ),
            ),
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    assert collection.replaced is not None
    assert collection.replaced["lines"][0]["pending_exit"] is True
    collection._document = collection.replaced
    loaded = store.get("701")
    assert loaded is not None
    assert loaded.lines[0].pending_exit is True


def test_micromarket_planogram_catch_up_requested_roundtrip() -> None:
    from src.application.micromarket_loading.shop_list import ShopListPublishStatus
    from src.infrastructure.mongodb.micromarket_planograms import (
        _planogram_from_document,
        _planogram_to_document,
    )

    doc = MicromarketPlanogram(
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
        updated_at=datetime(2026, 10, 1, tzinfo=UTC),
        shop_list_status=ShopListPublishStatus.PUBLISHING,
        shop_list_catch_up_requested=True,
    )
    raw = _planogram_to_document(doc)
    assert raw["shop_list_catch_up_requested"] is True
    restored = _planogram_from_document(raw)
    assert restored.shop_list_catch_up_requested is True
    without_key = _planogram_from_document(
        {k: v for k, v in raw.items() if k != "shop_list_catch_up_requested"}
    )
    assert without_key.shop_list_catch_up_requested is False
