from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.technician_warehouse.import_ms_transfers import (
    TechnicianWarehouseImportResult,
)

from .fakes import (
    _run_import,
    _supply_in,
    _supply_in_with_lines,
)


def test_import_truncates_non_domain_lines_keeps_domain() -> None:
    """happy: mix → domain-only; truncated_non_domain; unmatched empty; ref present."""
    result, warehouse = _run_import(
        _supply_in_with_lines("mix-1", ("coffee-rich", "10"), ("kit-outside", "2")),
    )
    assert result.imported == 1
    assert result.truncated_non_domain == 1
    assert result.unmatched_products == ()
    assert [ref.external_document_id for ref in result.transfer_refs] == ["mix-1"]
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("10")


def test_import_all_non_domain_observes_empty_lines() -> None:
    """edge: все non-domain → lines=(); imported растёт; hash = sha256(direction)."""
    import hashlib

    result, warehouse = _run_import(
        _supply_in("bad", product_code="unknown"),
    )
    assert result.imported == 1
    assert result.truncated_non_domain == 1
    assert result.unmatched_products == ()
    assert [ref.external_document_id for ref in result.transfer_refs] == ["bad"]
    expected_hash = hashlib.sha256(b"supply_in").hexdigest()
    assert result.transfer_refs[0].content_hash == expected_hash
    assert warehouse.calculated_stock_since_baseline() == {}
    assert "bad" in warehouse.observed_transfer_document_ids()


def test_import_partial_batch_imports_valid_and_truncates_non_domain() -> None:
    """happy: соседние moves — good + all-non-domain оба imported."""
    result, warehouse = _run_import(
        _supply_in("good"),
        _supply_in("bad", product_code="unknown"),
    )
    assert result.imported == 2
    assert result.truncated_non_domain == 1
    assert result.unmatched_products == ()
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("10")


def test_import_result_to_cli_dict_includes_truncated_non_domain() -> None:
    """happy: CLI shape."""
    result = TechnicianWarehouseImportResult(
        imported=0,
        updated=0,
        voided=0,
        ignored=0,
        skipped_unresolved=0,
        truncated_non_domain=3,
        transfer_refs=(),
        unmatched_products=(),
    )
    payload = result.to_cli_dict()
    assert payload["truncated_non_domain"] == 3
    assert payload["unmatched_products"] == []
    assert payload["skipped_unresolved"] == 0


def test_import_logs_truncate_info_not_unmatched_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """observability: truncate info; unmatched warning отсутствует."""
    import logging

    with caplog.at_level(logging.INFO):
        _run_import(_supply_in("bad", product_code="unknown"))
    messages = [r.getMessage() for r in caplog.records]
    assert any("technician_warehouse_ms_product_truncated" in m for m in messages)
    assert any("truncated_non_domain=" in m for m in messages)
    assert not any("technician_warehouse_ms_product_unmatched" in m for m in messages)
