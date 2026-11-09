from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from src.application.technician_warehouse.errors import TechnicianWarehouseImportBlocked
from src.application.technician_warehouse.import_ms_transfers import (
    format_unposted_ms_moves_blocker,
)

from .fakes import (
    _ANCHOR,
    _TECHNICIAN_ID,
    FakeTransferReader,
    _importer,
    _run_import,
    _supply_in,
    _technician_to_machine,
)


def test_import_unposted_supply_tech_raises_import_blocked_with_sample() -> None:
    unposted = replace(_supply_in("unposted-1"), applicable=False)
    reader = FakeTransferReader(moves=(unposted,))
    importer, _ = _importer(reader=reader)
    with pytest.raises(TechnicianWarehouseImportBlocked, match="unposted-1") as exc_info:
        asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    message = str(exc_info.value)
    assert message == format_unposted_ms_moves_blocker(document_ids=("unposted-1",))
    warehouse = importer.executor.repository.get(_TECHNICIAN_ID)
    assert warehouse.observed_transfer_document_ids() == frozenset()


def test_import_posted_supply_tech_still_imports() -> None:
    result, warehouse = _run_import(_supply_in("posted-1"))
    assert result.imported == 1
    assert "posted-1" in warehouse.observed_transfer_document_ids()


def test_import_only_unposted_window_raises_and_does_not_import() -> None:
    moves = (
        replace(_supply_in("u1"), applicable=False),
        replace(_supply_in("u2"), applicable=False),
    )
    reader = FakeTransferReader(moves=moves)
    importer, _ = _importer(reader=reader)
    with pytest.raises(TechnicianWarehouseImportBlocked, match="count=2"):
        asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert importer.executor.repository.get(_TECHNICIAN_ID).observed_transfer_document_ids() == (
        frozenset()
    )


def test_import_unposted_non_supply_tech_ignored_without_block() -> None:
    result, warehouse = _run_import(
        replace(_technician_to_machine("machine-unposted"), applicable=False),
    )
    assert result.imported == 0
    assert result.ignored == 1
    assert warehouse.observed_transfer_document_ids() == frozenset()


def test_import_mixed_posted_and_unposted_fails_closed_no_partial_import() -> None:
    reader = FakeTransferReader(
        moves=(
            _supply_in("posted-ok"),
            replace(_supply_in("unposted-bad"), applicable=False),
        ),
    )
    importer, _ = _importer(reader=reader)
    with pytest.raises(TechnicianWarehouseImportBlocked, match="unposted-bad"):
        asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert importer.executor.repository.get(_TECHNICIAN_ID).observed_transfer_document_ids() == (
        frozenset()
    )


def test_format_unposted_blocker_samples_at_most_five_sorted() -> None:
    ids = tuple(f"d{i}" for i in range(7, 0, -1))
    message = format_unposted_ms_moves_blocker(document_ids=ids)
    assert "count=7" in message
    assert "sample=d1,d2,d3,d4,d5" in message
    assert "d6" not in message.split("sample=", maxsplit=1)[1]
