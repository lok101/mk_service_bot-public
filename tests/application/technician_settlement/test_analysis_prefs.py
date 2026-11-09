from __future__ import annotations

from decimal import Decimal

from src.application.technician_settlement.analysis_prefs import SettlementAnalysisPrefs
from src.application.technician_settlement.analysis_prefs_memory import (
    InMemorySettlementAnalysisPrefsStore,
)


def test_prefs_load_missing_returns_empty() -> None:
    store = InMemorySettlementAnalysisPrefsStore()
    prefs = store.get(telegram_user_id=42)
    assert prefs.unit_prices == {}
    assert prefs.recoverable_product_codes == frozenset()
    assert prefs.allowed_loss_pct == Decimal("0")


def test_prefs_save_overwrite() -> None:
    store = InMemorySettlementAnalysisPrefsStore()
    first = SettlementAnalysisPrefs(
        unit_prices={"COFFEE": Decimal("1.5")},
        recoverable_product_codes=frozenset({"COFFEE"}),
        allowed_loss_pct=Decimal("2"),
    )
    store.save(telegram_user_id=7, prefs=first)
    second = SettlementAnalysisPrefs(
        unit_prices={"SUGAR": Decimal("0.1")},
        recoverable_product_codes=frozenset(),
        allowed_loss_pct=Decimal("1"),
    )
    store.save(telegram_user_id=7, prefs=second)
    got = store.get(7)
    assert got.unit_prices == {"SUGAR": Decimal("0.1")}
    assert got.recoverable_product_codes == frozenset()
    assert got.allowed_loss_pct == Decimal("1")
