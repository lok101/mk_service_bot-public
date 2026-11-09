from __future__ import annotations

from src.application.inventory_reconciliation.kitvending import (
    HOLDING_SKIP_ALERT_SAMPLE_SIZE,
    KitVendingFetchStats,
)


def test_holding_skip_sample_size_const() -> None:
    assert HOLDING_SKIP_ALERT_SAMPLE_SIZE == 5


def test_fetch_stats_holding_defaults() -> None:
    stats = KitVendingFetchStats()
    assert stats.holding_skip_count == 0
    assert stats.skipped_unresolved_product_non_holding == 0
    assert stats.hold_at is None
    assert stats.holding_samples == ()
    assert stats.fingerprint_pairs == ()
