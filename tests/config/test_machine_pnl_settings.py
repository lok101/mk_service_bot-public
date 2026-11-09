from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from src.config.machine_pnl import MachinePnlSettings
from src.config.settings import Settings
from src.domain.ids import MachineId
from src.infrastructure.composition.adapters.rent_accountant_alerter import (
    NoOpRentAccountantAlerter,
    build_rent_accountant_alerter,
)
from src.infrastructure.composition.adapters.zero_maintenance_alerter import (
    NoOpZeroMaintenanceAlerter,
    TelegramZeroMaintenanceAlerter,
    build_zero_maintenance_alerter,
)


def _stub_required_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_FORMS_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("REVISION_FORM_TOKEN_SECRET", "test-revision-secret")
    monkeypatch.setenv("LOADING_FORM_TOKEN_SECRET", "test-loading-secret")
    monkeypatch.setenv("REVISION_FORM_URL", "https://forms.example/revision")
    monkeypatch.setenv("LOADING_FORM_URL", "https://forms.example/loading")
    monkeypatch.setenv("REVISION_FORM_TOKEN_ENTRY_ID", "entry.1")
    monkeypatch.setenv("LOADING_FORM_TOKEN_ENTRY_ID", "entry.2")
    monkeypatch.setenv("GOOGLE_FORM_TOKEN_FIELD_NAME", "token")
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL",
        "https://forms.example/warehouse",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        "test-warehouse-inventory-secret",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
        "entry.3",
    )


def test_machine_pnl_disabled_skips_unit_cost_validation() -> None:
    s = MachinePnlSettings(MACHINE_PNL_ENABLED=False)
    assert s.enabled is False
    assert s.unit_cost_spreadsheet_id is None or s.unit_cost_spreadsheet_id == ""
    assert s.period_pnl_collection == "machine_period_pnl"


def test_machine_pnl_enabled_requires_unit_cost_ids() -> None:
    with pytest.raises(ValidationError):
        MachinePnlSettings(MACHINE_PNL_ENABLED=True)


def test_machine_pnl_enabled_requires_global_and_rent_ids() -> None:
    # error: unit cost alone insufficient
    with pytest.raises(ValidationError):
        MachinePnlSettings(
            MACHINE_PNL_ENABLED=True,
            MACHINE_PNL_UNIT_COST_SPREADSHEET_ID="ss-unit",
            MACHINE_PNL_UNIT_COST_SHEET_ID=1,
        )


def test_machine_pnl_enabled_accepts_global_and_rent_ids() -> None:
    # happy
    s = MachinePnlSettings(
        MACHINE_PNL_ENABLED=True,
        MACHINE_PNL_UNIT_COST_SPREADSHEET_ID="ss-unit",
        MACHINE_PNL_UNIT_COST_SHEET_ID=1,
        MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID="ss-global",
        MACHINE_PNL_GLOBAL_OPEX_SHEET_ID=10,
        MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID="ss-rent",
        MACHINE_PNL_LOCATION_RENT_SHEET_ID=20,
    )
    assert s.global_opex_spreadsheet_id == "ss-global"
    assert s.global_opex_sheet_id == 10
    assert s.location_rent_spreadsheet_id == "ss-rent"
    assert s.location_rent_sheet_id == 20


def test_machine_pnl_disabled_skips_global_rent_validation() -> None:
    # edge
    s = MachinePnlSettings(MACHINE_PNL_ENABLED=False)
    assert s.global_opex_spreadsheet_id is None
    assert s.location_rent_sheet_id is None


def test_machine_pnl_tax_disabled_skips_tax_sheet_ids() -> None:
    s = MachinePnlSettings(
        MACHINE_PNL_ENABLED=True,
        MACHINE_PNL_UNIT_COST_SPREADSHEET_ID="ss-unit",
        MACHINE_PNL_UNIT_COST_SHEET_ID=1,
        MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID="ss-global",
        MACHINE_PNL_GLOBAL_OPEX_SHEET_ID=10,
        MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID="ss-rent",
        MACHINE_PNL_LOCATION_RENT_SHEET_ID=20,
        MACHINE_PNL_TAX_ENABLED=False,
    )
    assert s.tax_enabled is False
    assert s.tax_spreadsheet_id is None
    assert s.tax_sheet_id is None


def test_machine_pnl_tax_enabled_without_tax_sheet_ids_ok() -> None:
    # happy: TAX_ENABLED without TAX_* ids — no ValidationError (loader not implemented)
    s = MachinePnlSettings(
        MACHINE_PNL_ENABLED=True,
        MACHINE_PNL_UNIT_COST_SPREADSHEET_ID="ss-unit",
        MACHINE_PNL_UNIT_COST_SHEET_ID=1,
        MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID="ss-global",
        MACHINE_PNL_GLOBAL_OPEX_SHEET_ID=10,
        MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID="ss-rent",
        MACHINE_PNL_LOCATION_RENT_SHEET_ID=20,
        MACHINE_PNL_TAX_ENABLED=True,
    )
    assert s.tax_enabled is True
    assert s.tax_spreadsheet_id is None
    assert s.tax_sheet_id is None


def test_machine_pnl_tax_enabled_accepts_tax_sheet_ids() -> None:
    s = MachinePnlSettings(
        MACHINE_PNL_ENABLED=True,
        MACHINE_PNL_UNIT_COST_SPREADSHEET_ID="ss-unit",
        MACHINE_PNL_UNIT_COST_SHEET_ID=1,
        MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID="ss-global",
        MACHINE_PNL_GLOBAL_OPEX_SHEET_ID=10,
        MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID="ss-rent",
        MACHINE_PNL_LOCATION_RENT_SHEET_ID=20,
        MACHINE_PNL_TAX_ENABLED=True,
        MACHINE_PNL_TAX_SPREADSHEET_ID="ss-tax",
        MACHINE_PNL_TAX_SHEET_ID=2,
    )
    assert s.tax_enabled is True
    assert s.tax_spreadsheet_id == "ss-tax"
    assert s.tax_sheet_id == 2


def test_machine_pnl_alert_chat_id_optional_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MACHINE_PNL_ENABLED", "false")
    monkeypatch.delenv("MACHINE_PNL_ALERT_CHAT_ID", raising=False)
    settings = MachinePnlSettings()
    assert settings.alert_chat_id is None

    monkeypatch.setenv("MACHINE_PNL_ALERT_CHAT_ID", "")
    assert MachinePnlSettings().alert_chat_id is None

    monkeypatch.setenv("MACHINE_PNL_ALERT_CHAT_ID", "12345")
    assert MachinePnlSettings().alert_chat_id == 12345


def test_machine_pnl_rent_pending_env_defaults_and_validation() -> None:
    s = MachinePnlSettings(enabled=False)
    assert s.rent_pending_retry_hours == 24
    assert s.rent_pending_max_attempts == 7
    assert s.rent_accountant_chat_id is None


def test_machine_pnl_rent_pending_hours_must_be_ge_one() -> None:
    with pytest.raises(ValidationError):
        MachinePnlSettings(enabled=False, rent_pending_retry_hours=0)


def test_machine_pnl_rent_accountant_chat_id_empty_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MACHINE_PNL_ENABLED", "false")
    monkeypatch.setenv("MACHINE_PNL_RENT_ACCOUNTANT_CHAT_ID", "")
    assert MachinePnlSettings().rent_accountant_chat_id is None

    monkeypatch.setenv("MACHINE_PNL_RENT_ACCOUNTANT_CHAT_ID", "99901")
    assert MachinePnlSettings().rent_accountant_chat_id == 99901


def test_rent_accountant_alerter_noop_when_chat_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.delenv("MACHINE_PNL_RENT_ACCOUNTANT_CHAT_ID", raising=False)
    alerter = build_rent_accountant_alerter(Settings())
    assert isinstance(alerter, NoOpRentAccountantAlerter)
    alerter.notify(
        period_id="p-1",
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        next_retry_hours=24,
    )


def test_build_zero_maintenance_alerter_noop_when_chat_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.delenv("MACHINE_PNL_ALERT_CHAT_ID", raising=False)
    alerter = build_zero_maintenance_alerter(Settings())
    assert isinstance(alerter, NoOpZeroMaintenanceAlerter)
    alerter.notify(
        period_id="p1",
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        maintenance_count=0,
    )


def test_build_zero_maintenance_alerter_noop_when_bot_token_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MACHINE_PNL_ALERT_CHAT_ID", "12345")
    monkeypatch.setenv("BOT_TOKEN", "   ")
    alerter = build_zero_maintenance_alerter(Settings())
    assert isinstance(alerter, NoOpZeroMaintenanceAlerter)


def test_telegram_zero_maintenance_alerter_soft_fails_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error",
        request=httpx.Request("POST", "https://api.telegram.org/botx/sendMessage"),
        response=httpx.Response(500),
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.adapters.zero_maintenance_alerter.httpx.post",
        lambda *args, **kwargs: response,
    )
    alerter = TelegramZeroMaintenanceAlerter(bot_token="tok", chat_id=42)
    alerter.notify(
        period_id="p1",
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        maintenance_count=0,
    )


def test_machine_pnl_catalog_cache_ttl_default_and_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy
    monkeypatch.setenv("MACHINE_PNL_ENABLED", "false")
    monkeypatch.delenv("MACHINE_PNL_CATALOG_CACHE_TTL_SECONDS", raising=False)
    assert MachinePnlSettings().catalog_cache_ttl_seconds == 1800

    monkeypatch.setenv("MACHINE_PNL_CATALOG_CACHE_TTL_SECONDS", "300")
    assert MachinePnlSettings().catalog_cache_ttl_seconds == 300


def test_machine_pnl_catalog_cache_ttl_must_be_at_least_60(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # error
    monkeypatch.setenv("MACHINE_PNL_ENABLED", "false")
    monkeypatch.setenv("MACHINE_PNL_CATALOG_CACHE_TTL_SECONDS", "10")
    with pytest.raises(ValidationError):
        MachinePnlSettings()
