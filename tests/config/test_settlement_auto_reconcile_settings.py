from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.application.outbox.handler_ids import (
    SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
    SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
)
from src.config.mongodb import MongoSettings
from src.config.settlement import SettlementSettings


def test_portion_handler_ids() -> None:
    assert SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID == "settlement_portion_sync_transfers"
    assert SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID == "settlement_portion_sales_verify"
    assert SETTLEMENT_PORTION_RECONCILE_HANDLER_ID == "settlement_portion_reconcile"


def test_auto_reconcile_defaults_disabled() -> None:
    settings = SettlementSettings()
    assert settings.auto_reconcile_enabled is False


def test_auto_reconcile_enabled_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SETTLEMENT_AUTO_RECONCILE_ENABLED", "true")
    settings = SettlementSettings()
    assert settings.auto_reconcile_enabled is True


def test_portion_reconcile_quarantine_seconds_default() -> None:
    # happy: default 86400 (24h)
    settings = SettlementSettings()
    assert settings.portion_reconcile_quarantine_seconds == 86400


def test_portion_reconcile_quarantine_seconds_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # happy: overridable via env
    monkeypatch.setenv("SETTLEMENT_PORTION_RECONCILE_QUARANTINE_SECONDS", "0")
    settings = SettlementSettings()
    assert settings.portion_reconcile_quarantine_seconds == 0


def test_portion_reconcile_quarantine_seconds_rejects_negative() -> None:
    # error: ge=0
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        SettlementSettings(SETTLEMENT_PORTION_RECONCILE_QUARANTINE_SECONDS=-1)


def test_machine_sales_skipped_collection_default() -> None:
    mongo = MongoSettings()
    assert mongo.machine_sales_skipped_collection == "machine_sales_skipped"


def test_machine_sales_skipped_collection_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_MACHINE_SALES_SKIPPED_COLLECTION", "skips_custom")
    mongo = MongoSettings()
    assert mongo.machine_sales_skipped_collection == "skips_custom"
