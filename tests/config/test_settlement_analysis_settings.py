from __future__ import annotations

from pydantic import ValidationError

from src.config.settlement_analysis import SettlementAnalysisSettings


def test_settlement_analysis_disabled_by_default() -> None:
    s = SettlementAnalysisSettings()
    assert s.enabled is False
    assert s.prefs_collection == "settlement_analysis_prefs"


def test_settlement_analysis_requires_session_secret() -> None:
    try:
        SettlementAnalysisSettings(
            SETTLEMENT_ANALYSIS_ADMIN_ENABLED="true",
            ADMIN_SESSION_SECRET="",
            TELEGRAM_BOT_USERNAME="bot",
        )
    except ValidationError:
        return
    raise AssertionError("expected ValidationError")
