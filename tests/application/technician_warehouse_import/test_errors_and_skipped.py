from __future__ import annotations

import asyncio

import pytest

from src.application.technician_warehouse.errors import MoySkladUnavailable
from src.application.technician_warehouse.import_ms_transfers import (
    TechnicianWarehouseImportResult,
)

from .fakes import (
    _ANCHOR,
    _TECHNICIAN_ID,
    ErrorTransferReader,
    FakeTransferReader,
    _importer,
    _supply_in,
)


def test_import_propagates_moysklad_unavailable_from_reader() -> None:
    importer, _ = _importer(reader=ErrorTransferReader(error=MoySkladUnavailable("timeout")))
    with pytest.raises(MoySkladUnavailable, match="timeout"):
        asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))


def test_import_result_to_cli_dict_includes_skipped_unresolved_int_only() -> None:
    result = TechnicianWarehouseImportResult(
        imported=0,
        updated=0,
        voided=0,
        ignored=0,
        skipped_unresolved=3,
        truncated_non_domain=0,
        transfer_refs=(),
        unmatched_products=(),
    )
    payload = result.to_cli_dict()
    assert payload["skipped_unresolved"] == 3
    assert "sample" not in payload
    assert not any(isinstance(v, list) and v and "move" in str(v) for v in payload.values())


def test_import_propagates_skipped_unresolved_from_reader() -> None:
    reader = FakeTransferReader(
        moves=(_supply_in("in-1"),),
        skipped_unresolved=2,
    )
    importer, _ = _importer(reader=reader)
    result = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert result.skipped_unresolved == 2
    assert result.imported == 1
