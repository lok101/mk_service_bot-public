from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
)
from src.domain.product_catalog import ProductSpec, ProductUnit, default_moysklad_quantity_factor
from src.infrastructure.integrations.moysklad.product_spec_resolver import (
    MappingProductSpecByCodeResolver,
)
from src.infrastructure.integrations.moysklad.warehouse_move_quantity import (
    MoySkladCatalogBaseQuantityResolver,
)

from .fakes import (
    _ANCHOR,
    _T2,
    _TECHNICIAN_ID,
    FakeTransferReader,
    _importer,
    _importer_with_finalized_move,
    _repeatable_import_case,
    _repository,
    _run_import,
    _supply_in,
    _supply_in_with_lines,
)


@pytest.mark.parametrize("empty_code", ["", "   "])
def test_import_skips_document_with_empty_product_code(
    empty_code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """error: empty/whitespace code → skip doc; сосед imported; truncated не растёт."""
    import logging

    empty_line_move = _supply_in_with_lines("bad-empty", (empty_code, "1"))
    good = _supply_in("good")
    with caplog.at_level(logging.WARNING):
        result, warehouse = _run_import(empty_line_move, good)
    assert result.imported == 1
    assert result.truncated_non_domain == 0
    assert "bad-empty" not in {ref.external_document_id for ref in result.transfer_refs}
    assert "good" in {ref.external_document_id for ref in result.transfer_refs}
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("10")
    assert any(
        "technician_warehouse_ms_invalid_product_code" in r.getMessage() for r in caplog.records
    )


def test_reimport_with_empty_product_code_voids_previously_observed_transfer() -> None:
    """edge: после valid observe empty code не держит doc в seen → void, stock сбрасывается."""
    repository = _repository()
    reader = FakeTransferReader(moves=(_supply_in("move-1"),))
    importer, _ = _importer(reader=reader, repository=repository)

    first = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert first.imported == 1
    assert repository.get(_TECHNICIAN_ID).calculated_stock_since_baseline()["coffee"] == (
        Decimal("10")
    )

    reader.moves = (_supply_in_with_lines("move-1", ("", "1")),)
    second = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert second.voided == 1
    assert second.imported == 0
    assert second.updated == 0
    assert second.truncated_non_domain == 0
    assert "move-1" not in {ref.external_document_id for ref in second.transfer_refs}
    assert repository.get(_TECHNICIAN_ID).calculated_stock_since_baseline() == {}


def test_reimport_after_catalog_add_updates_empty_transfer_with_domain_lines() -> None:
    """edge: сначала truncate-all (empty observe); после кода в map → updated + stock."""
    specs: dict[str, ProductSpec] = {}
    product_resolver = MappingProductSpecByCodeResolver(specs)
    catalog = MoySkladCatalogBaseQuantityResolver(product_resolver=product_resolver)
    repository = _repository()
    reader = FakeTransferReader(
        moves=(_supply_in("move-kit", product_code="kit-1", quantity="4"),),
    )
    importer = ImportTechnicianWarehouseTransfers(
        reader=reader,
        catalog_base_quantity_resolver=catalog,
        executor=TechnicianWarehouseExecutor(repository=repository),
        supply_store_codes=("main",),
        lookback_days=60,
    )

    first = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert first.imported == 1
    assert first.truncated_non_domain == 1
    assert repository.get(_TECHNICIAN_ID).calculated_stock_since_baseline() == {}

    unit = ProductUnit.PIECE
    specs["kit-1"] = ProductSpec(
        product_code="kit-1",
        name="Kit",
        unit=unit,
        pack_size=Decimal("1"),
        min_stock=None,
        max_stock=None,
        allow_fraction=False,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )

    second = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert second.updated == 1
    assert second.truncated_non_domain == 0
    assert repository.get(_TECHNICIAN_ID).calculated_stock_since_baseline()["kit-1"] == (
        Decimal("4")
    )


def test_reimport_changed_open_document_appends_latest_observation() -> None:
    importer, repository = _repeatable_import_case()
    asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    importer.reader.moves = (_supply_in("move-1", quantity="12", updated_at=_T2),)
    result = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert result.updated == 1
    assert repository.get(_TECHNICIAN_ID).calculated_stock_since_baseline()["coffee"] == 12


def test_reimport_missing_open_document_appends_void() -> None:
    importer, repository = _repeatable_import_case()
    asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    importer.reader.moves = ()
    result = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert result.voided == 1
    assert repository.get(_TECHNICIAN_ID).calculated_stock_since_baseline() == {}


def test_changed_finalized_document_is_ignored() -> None:
    importer = _importer_with_finalized_move("move-1")
    before = importer.executor.repository.get(_TECHNICIAN_ID)
    before_hash = before.non_voided_transfers()[0].content_hash
    before_qty = before.calculated_stock_since_baseline().get("coffee")
    importer.reader.moves = (_supply_in("move-1", quantity="12", updated_at=_T2),)
    result = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert result.ignored >= 1
    assert len(result.ignored_finalized_transfers) == 1
    ignored = result.ignored_finalized_transfers[0]
    assert ignored.external_document_id == "move-1"
    assert ignored.kind == "changed"
    assert all(ref.external_document_id != "move-1" for ref in result.transfer_refs)
    after = importer.executor.repository.get(_TECHNICIAN_ID)
    assert after.non_voided_transfers()[0].content_hash == before_hash
    assert after.calculated_stock_since_baseline().get("coffee") == before_qty


def test_missing_finalized_document_is_ignored_not_voided() -> None:
    importer = _importer_with_finalized_move("move-1")
    importer.reader.moves = ()
    result = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert result.voided == 0
    assert len(result.ignored_finalized_transfers) == 1
    assert result.ignored_finalized_transfers[0].kind == "missing"
    assert (
        "move-1"
        in importer.executor.repository.get(
            _TECHNICIAN_ID,
        ).observed_transfer_document_ids()
    )
