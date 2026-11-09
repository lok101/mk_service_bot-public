from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation.ports import SnackMachineLayoutStore
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_planogram import (
    SNACK_PLANOGRAM_DEFAULT_SHELF_COUNT,
    SNACK_PLANOGRAM_DEFAULT_SLOTS_PER_SHELF,
    SnackPlanogramMerge,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class SnackMachineLayoutsCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...


@beartype
def _cell_to_document(cell: SnackMachineLayoutCell) -> dict[str, Any]:
    cell_doc: dict[str, Any] = {
        "line_number": cell.line_number,
        "product_code": cell.product_code,
    }
    if cell.shelf_index is not None:
        cell_doc["shelf_index"] = cell.shelf_index
    if cell.slot_index is not None:
        cell_doc["slot_index"] = cell.slot_index
    if cell.domain_product_id is not None:
        cell_doc["domain_product_id"] = cell.domain_product_id
    return cell_doc


@beartype
def _cell_from_document(cell_raw: dict[str, Any]) -> SnackMachineLayoutCell:
    line_number = cell_raw.get("line_number")
    product_code = cell_raw.get("product_code")
    if not isinstance(line_number, int):
        raise ValueError("line_number must be int")
    if product_code is not None and not isinstance(product_code, str):
        raise ValueError("product_code must be str or None")
    shelf_index = cell_raw.get("shelf_index")
    slot_index = cell_raw.get("slot_index")
    if shelf_index is not None and not isinstance(shelf_index, int):
        raise ValueError("shelf_index must be int or omitted")
    if slot_index is not None and not isinstance(slot_index, int):
        raise ValueError("slot_index must be int or omitted")
    domain_product_raw = cell_raw.get("domain_product_id")
    if domain_product_raw is None:
        domain_product_id: str | None = None
    elif isinstance(domain_product_raw, str):
        domain_product_id = domain_product_raw
    else:
        raise ValueError("domain_product_id must be str or None")
    return SnackMachineLayoutCell(
        line_number=line_number,
        product_code=product_code,
        shelf_index=shelf_index,
        slot_index=slot_index,
        domain_product_id=domain_product_id,
    )


@beartype
def _layout_to_document(layout: SnackMachineLayout) -> dict[str, Any]:
    return {
        "_id": layout.machine_code,
        "logical_matrix_name": layout.logical_matrix_name,
        "matrix_multiplier": str(layout.matrix_multiplier),
        "auto_sync_enabled": layout.auto_sync_enabled,
        "cells": [_cell_to_document(cell) for cell in layout.cells],
        "shelf_count": layout.shelf_count,
        "slots_per_shelf": layout.slots_per_shelf,
        "merges": [
            {"shelf_index": merge.shelf_index, "slot_index": merge.slot_index}
            for merge in layout.merges
        ],
    }


@beartype
def _layout_from_document(document: dict[str, Any]) -> SnackMachineLayout:
    id_raw = document.get("_id", document.get("machine_code"))
    logical_matrix_name = document.get("logical_matrix_name")
    multiplier_raw = document.get("matrix_multiplier")
    auto_sync_enabled = document.get("auto_sync_enabled")
    cells_raw = document.get("cells")
    shelf_count_raw = document.get("shelf_count", SNACK_PLANOGRAM_DEFAULT_SHELF_COUNT)
    slots_per_shelf_raw = document.get(
        "slots_per_shelf",
        SNACK_PLANOGRAM_DEFAULT_SLOTS_PER_SHELF,
    )
    merges_raw = document.get("merges", [])
    if not isinstance(id_raw, str):
        raise ValueError("machine_code must be str")
    if not isinstance(logical_matrix_name, str):
        raise ValueError("logical_matrix_name must be str")
    if not isinstance(auto_sync_enabled, bool):
        raise ValueError("auto_sync_enabled must be bool")
    if not isinstance(cells_raw, list):
        raise ValueError("cells must be list")
    if not isinstance(shelf_count_raw, int):
        raise ValueError("shelf_count must be int")
    if not isinstance(slots_per_shelf_raw, int):
        raise ValueError("slots_per_shelf must be int")
    if not isinstance(merges_raw, list):
        raise ValueError("merges must be list")
    try:
        matrix_multiplier = Decimal(str(multiplier_raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("matrix_multiplier must be Decimal-compatible") from exc
    cells: list[SnackMachineLayoutCell] = []
    for cell_raw in cells_raw:
        if not isinstance(cell_raw, dict):
            raise ValueError("cell must be dict")
        cells.append(_cell_from_document(cell_raw))
    merges: list[SnackPlanogramMerge] = []
    for merge_raw in merges_raw:
        if not isinstance(merge_raw, dict):
            raise ValueError("merge must be dict")
        shelf_index = merge_raw.get("shelf_index")
        slot_index = merge_raw.get("slot_index")
        if not isinstance(shelf_index, int):
            raise ValueError("shelf_index must be int")
        if not isinstance(slot_index, int):
            raise ValueError("slot_index must be int")
        merges.append(SnackPlanogramMerge(shelf_index=shelf_index, slot_index=slot_index))
    return SnackMachineLayout(
        machine_code=id_raw,
        logical_matrix_name=logical_matrix_name,
        matrix_multiplier=matrix_multiplier,
        auto_sync_enabled=auto_sync_enabled,
        cells=tuple(cells),
        shelf_count=shelf_count_raw,
        slots_per_shelf=slots_per_shelf_raw,
        merges=tuple(merges),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoSnackMachineLayoutStore(SnackMachineLayoutStore):
    collection: SnackMachineLayoutsCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoSnackMachineLayoutStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.snack_machine_layouts_collection,
            owner="MongoSnackMachineLayoutStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self, machine_code: str) -> SnackMachineLayout | None:
        document = self.collection.find_one({"_id": machine_code})
        if document is None:
            return None
        return _layout_from_document(document)

    @beartype
    def upsert(self, layout: SnackMachineLayout) -> None:
        self.collection.replace_one(
            {"_id": layout.machine_code},
            _layout_to_document(layout),
            upsert=True,
        )

    @beartype
    def list_all(self) -> tuple[SnackMachineLayout, ...]:
        items: list[SnackMachineLayout] = []
        for document in self.collection.find({}):
            if isinstance(document, dict):
                items.append(_layout_from_document(document))
        items.sort(key=lambda layout: layout.machine_code)
        return tuple(items)

    @beartype
    def count(self) -> int:
        return int(self.collection.count_documents({}))
