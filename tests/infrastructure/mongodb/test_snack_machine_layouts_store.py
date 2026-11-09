from __future__ import annotations

from decimal import Decimal

import mongomock

from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_planogram import SnackPlanogramMerge
from src.infrastructure.mongodb.snack_machine_layouts import (
    MongoSnackMachineLayoutStore,
    _layout_from_document,
    _layout_to_document,
)


def _make_store() -> MongoSnackMachineLayoutStore:
    db = mongomock.MongoClient().db
    return MongoSnackMachineLayoutStore(collection=db["snack_machine_layouts"])


def test_layout_from_document_defaults_planogram_6x10() -> None:
    layout = _layout_from_document(
        {
            "_id": "512",
            "logical_matrix_name": "512",
            "matrix_multiplier": "1",
            "auto_sync_enabled": True,
            "cells": [],
        }
    )
    assert layout.shelf_count == 6
    assert layout.slots_per_shelf == 10
    assert layout.merges == ()


def test_mongo_layout_roundtrip_with_planogram() -> None:
    original = SnackMachineLayout(
        machine_code="512",
        logical_matrix_name="Tab",
        matrix_multiplier=Decimal("1.2"),
        auto_sync_enabled=True,
        cells=(SnackMachineLayoutCell(line_number=11, product_code="SKU1"),),
        shelf_count=6,
        slots_per_shelf=12,
        merges=(SnackPlanogramMerge(shelf_index=4, slot_index=0),),
    )
    assert _layout_from_document(_layout_to_document(original)) == original


def test_layout_document_roundtrip() -> None:
    original = SnackMachineLayout(
        machine_code="514",
        logical_matrix_name="Tab",
        matrix_multiplier=Decimal("1.2"),
        auto_sync_enabled=True,
        cells=(
            SnackMachineLayoutCell(line_number=1, product_code="SKU1"),
            SnackMachineLayoutCell(line_number=2, product_code=None),
        ),
    )
    assert _layout_from_document(_layout_to_document(original)) == original


def test_mongo_layout_store_allows_duplicate_names() -> None:
    db = mongomock.MongoClient().db
    store = MongoSnackMachineLayoutStore(collection=db["snack_machine_layouts"])
    store.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="SameTab",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    store.upsert(
        SnackMachineLayout(
            machine_code="515",
            logical_matrix_name="SameTab",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(),
        )
    )
    assert store.count() == 2
    assert store.get("514").logical_matrix_name == "SameTab"
    assert store.get("515").logical_matrix_name == "SameTab"


def test_mongo_layout_roundtrip_with_cell_coords() -> None:
    layout = SnackMachineLayout(
        machine_code="512",
        logical_matrix_name="512",
        matrix_multiplier=Decimal("1"),
        auto_sync_enabled=True,
        cells=(
            SnackMachineLayoutCell(11, "SKU1", 0, 0),
            SnackMachineLayoutCell(19, "AQUA", 0, 7),
        ),
    )
    store = _make_store()
    store.upsert(layout)
    loaded = store.get("512")
    assert loaded == layout


def test_layout_from_document_legacy_cell_without_coords() -> None:
    doc = {
        "_id": "512",
        "logical_matrix_name": "512",
        "matrix_multiplier": "1",
        "auto_sync_enabled": True,
        "cells": [{"line_number": 5, "product_code": "OLD"}],
        "shelf_count": 6,
        "slots_per_shelf": 10,
        "merges": [],
    }
    layout = _layout_from_document(doc)
    assert layout.cells == (SnackMachineLayoutCell(5, "OLD"),)


def test_layout_to_document_cells_kit_fields_only_required() -> None:
    layout = SnackMachineLayout(
        machine_code="512",
        logical_matrix_name="512",
        matrix_multiplier=Decimal("1"),
        auto_sync_enabled=True,
        cells=(SnackMachineLayoutCell(11, "SKU1", 0, 0),),
    )
    doc = _layout_to_document(layout)
    assert doc["cells"] == [
        {
            "line_number": 11,
            "product_code": "SKU1",
            "shelf_index": 0,
            "slot_index": 0,
        },
    ]
