from __future__ import annotations

import pytest
from tests.application.matrix_automation.substitution_guard.fakes import (
    _build_one,
    _build_two_cells,
    _extra,
    _PerCellStockProvider,
    _record,
)


def test_stock_provider_exception_blocks_only_affected_cell(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    provider = _PerCellStockProvider({1: RuntimeError("stock down"), 2: 0})
    with caplog.at_level(logging.INFO):
        result = _build_two_cells(provider=provider, job_id="job-42")
    first, second = result.payloads[0].lines
    assert (first.outcome, first.reason) == ("product_swap_blocked", "stock_unknown")
    assert second.outcome == "applied"
    failed = _record(caplog, "matrix_stock_fetch_failed")
    assert failed.levelname == "WARNING"
    assert _extra(failed) == {
        "job_id": "job-42",
        "machine_code": "512",
        "logical_matrix_name": "Snacks",
        "line_number": 1,
        "product_code": "OLD-1",
        "error": "stock down",
    }
    blocked = _record(caplog, "matrix_substitution_blocked")
    assert blocked.levelname == "INFO"
    assert blocked.job_id == "job-42"
    assert blocked.machine_code == "512"
    assert blocked.logical_matrix_name == "Snacks"
    assert blocked.line_number == 1
    assert blocked.current_product == "OLD-1"
    assert blocked.desired_product == "NEW-1"
    assert blocked.observed_stock is None
    assert blocked.block_reason == "stock_unknown"


def test_blocked_decision_logs_required_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.INFO):
        _build_one(desired=None, current="OLD", stock=3, guard_enabled=True, job_id="test")
    record = _record(caplog, "matrix_substitution_blocked")
    assert record.levelname == "INFO"
    assert record.desired_product is None
    assert record.observed_stock == 3
    assert record.block_reason == "stock_positive"
    assert record.job_id == "test"
    assert record.machine_code == "512"
    assert record.logical_matrix_name == "Snacks"
    assert record.line_number == 1
    assert record.current_product == "OLD"


def test_allow_path_has_no_blocked_log(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.INFO):
        _build_one(desired="NEW", current="OLD", stock=0, guard_enabled=True, job_id="test")
    assert not any(
        record.getMessage() == "matrix_substitution_blocked" for record in caplog.records
    )


def test_direct_builder_logs_use_test_job_id_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.INFO):
        _build_one(desired="NEW", current="OLD", stock=1, guard_enabled=True)
    assert _record(caplog, "matrix_substitution_blocked").job_id == "test"
