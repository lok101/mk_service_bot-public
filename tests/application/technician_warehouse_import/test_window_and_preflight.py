from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from src.application.technician_warehouse.errors import TechnicianWarehouseImportBlocked

from .fakes import (
    _ANCHOR,
    _PREVIOUS,
    _TECHNICIAN_ID,
    FakeTransferReader,
    _importer,
    _supply_in,
)


def test_import_uses_previous_finalized_inventory_minus_lookback() -> None:
    importer, reader = _importer(previous_inventory_at=_PREVIOUS, lookback_days=60)
    asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert reader.calls[0][0] == _PREVIOUS - timedelta(days=60)


def test_import_falls_back_to_anchor_minus_lookback_without_previous_inventory() -> None:
    importer, reader = _importer(previous_inventory_at=None, lookback_days=60)
    asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert reader.calls[0][0] == _ANCHOR - timedelta(days=60)


def test_import_blocks_when_supply_store_codes_empty() -> None:
    importer, reader = _importer(supply_store_codes=())
    with pytest.raises(TechnicianWarehouseImportBlocked, match="SUPPLY_STORE_CODES"):
        asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert reader.ensure_calls == []
    assert reader.calls == []


def test_import_blocks_when_supply_store_code_missing_in_ms() -> None:
    """error: preflight → TechnicianWarehouseImportBlocked; read_moves не вызывается."""
    reader = FakeTransferReader(
        ensure_error=TechnicianWarehouseImportBlocked(
            "TECHNICIAN_WAREHOUSE_SUPPLY_STORE_CODES: store code 'ghost' not found",
        ),
        moves=(_supply_in("should-not-read"),),
    )
    importer, _ = _importer(reader=reader, supply_store_codes=("main", "ghost"))
    with pytest.raises(TechnicianWarehouseImportBlocked, match="ghost"):
        asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert reader.ensure_calls == [("main", "ghost")]
    assert reader.calls == []


def test_import_calls_ensure_before_read_moves() -> None:
    """happy: порядок ensure → read_moves."""
    reader = FakeTransferReader(moves=(_supply_in("in-1"),))
    importer, _ = _importer(reader=reader, supply_store_codes=("main",))
    asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert reader.ensure_calls == [("main",)]
    assert len(reader.calls) == 1
