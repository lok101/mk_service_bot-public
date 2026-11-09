from __future__ import annotations

import logging

import pytest

from src.infrastructure.composition.wiring.wire_sales_monitoring_worker import (
    run_offline_poll_safely,
)
from src.infrastructure.integrations.kitvending.http_client import KitVendingNetworkError


def test_run_offline_poll_safely_swallows_kit_network_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # error recovery
    def boom() -> None:
        raise KitVendingNetworkError("503 after retry")

    caplog.set_level(logging.WARNING)
    run_offline_poll_safely(execute=boom)
    assert any(
        "sales_monitoring_offline_poll_kit_network" in record.getMessage()
        for record in caplog.records
    )
    assert all(record.levelno < logging.ERROR for record in caplog.records)


def test_run_offline_poll_safely_propagates_success() -> None:
    # happy
    calls = {"n": 0}

    def ok() -> None:
        calls["n"] += 1

    run_offline_poll_safely(execute=ok)
    assert calls["n"] == 1


def test_run_offline_poll_safely_does_not_swallow_other_errors() -> None:
    # edge: прочий exception не маскировать
    def boom() -> None:
        raise RuntimeError("catalog missing")

    with pytest.raises(RuntimeError, match="catalog missing"):
        run_offline_poll_safely(execute=boom)
