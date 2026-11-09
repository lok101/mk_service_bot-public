from __future__ import annotations

from tests.application.matrix_automation.substitution_guard.fakes import (
    _build_one,
    _RecordingStockProvider,
)


def test_guard_disabled_keeps_phase3_payload_and_never_calls_provider() -> None:
    provider = _RecordingStockProvider(stock=10)
    line = _build_one(desired="NEW", current="OLD", guard_enabled=False, provider=provider)
    assert line.product_code == "NEW"
    assert line.outcome == "applied"
    assert provider.calls == []


def test_first_deploy_has_no_guard_provider_call() -> None:
    provider = _RecordingStockProvider(stock=10)
    line = _build_one(desired="NEW", current=None, guard_enabled=True, provider=provider)
    assert (line.product_code, line.outcome) == ("NEW", "applied")
    assert provider.calls == []


def test_empty_snapshot_product_to_new_has_no_guard_provider_call() -> None:
    provider = _RecordingStockProvider(stock=10)
    line = _build_one(
        desired="NEW",
        current=None,
        current_snapshot_outcome="blocked_empty",
        guard_enabled=True,
        provider=provider,
    )
    assert (line.product_code, line.outcome) == ("NEW", "applied")
    assert provider.calls == []


def test_same_product_has_no_guard_provider_call() -> None:
    provider = _RecordingStockProvider(stock=10)
    line = _build_one(desired="SAME", current="SAME", guard_enabled=True, provider=provider)
    assert line.product_code == "SAME"
    assert provider.calls == []
