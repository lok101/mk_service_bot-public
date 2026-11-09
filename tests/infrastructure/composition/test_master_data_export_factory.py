from __future__ import annotations

from pathlib import Path

import pytest

from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.config.settings import Settings
from src.infrastructure.composition.factories.master_data import build_master_data_export_hook
from src.infrastructure.reference_data.master_data_sheets_export import GoogleSheetsMasterDataExport


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
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)


def test_build_export_hook_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MASTER_DATA_SHEETS_EXPORT_ENABLED", "false")
    settings = Settings()
    hook = build_master_data_export_hook(
        settings,
        roster_store=InMemoryLocationRosterStore(),
        technician_names={},
        company_names_provider=lambda _stores: {},
    )
    assert hook is None


def test_build_export_hook_mirror_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _stub_required_app_env(monkeypatch)
    credentials = tmp_path / "creds.json"
    credentials.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("MASTER_DATA_SHEETS_EXPORT_ENABLED", "true")
    monkeypatch.setenv("MASTER_DATA_MIRROR_SPREADSHEET_ID", "mirror-book")
    monkeypatch.setenv("MASTER_DATA_MIRROR_LOCATIONS_SHEET_ID", "11")
    monkeypatch.setenv("MASTER_DATA_MIRROR_MACHINES_SHEET_ID", "12")
    settings = Settings()
    hook = build_master_data_export_hook(
        settings,
        roster_store=InMemoryLocationRosterStore(),
        technician_names={},
        company_names_provider=lambda _stores: {},
    )
    assert isinstance(hook, GoogleSheetsMasterDataExport)
    assert hook.locations.spreadsheet_id == "mirror-book"
    assert hook.locations.sheet_id == 11
    assert hook.machines.spreadsheet_id == "mirror-book"
    assert hook.machines.sheet_id == 12
