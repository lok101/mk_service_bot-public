from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.google_forms import GoogleFormsSettings

_WAREHOUSE_FORM_URL = "https://forms.example/warehouse"
_WAREHOUSE_TOKEN_SECRET = "wh-inv"
_WAREHOUSE_TOKEN_ENTRY_ID = "entry.3"


def _set_required_google_forms_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_FORMS_WEBHOOK_SECRET", "wh")
    monkeypatch.setenv("REVISION_FORM_TOKEN_SECRET", "rev")
    monkeypatch.setenv("LOADING_FORM_TOKEN_SECRET", "load")
    monkeypatch.setenv("REVISION_FORM_URL", "https://forms.example/revision")
    monkeypatch.setenv("LOADING_FORM_URL", "https://forms.example/loading")
    monkeypatch.setenv("REVISION_FORM_TOKEN_ENTRY_ID", "entry.1")
    monkeypatch.setenv("LOADING_FORM_TOKEN_ENTRY_ID", "entry.2")
    monkeypatch.setenv("GOOGLE_FORM_TOKEN_FIELD_NAME", "token")


def test_google_forms_settings_require_warehouse_inventory_form_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_google_forms_env(monkeypatch)
    for key in (
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL",
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        GoogleFormsSettings()


def test_google_forms_settings_accept_warehouse_inventory_form_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_google_forms_env(monkeypatch)
    monkeypatch.setenv("TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL", _WAREHOUSE_FORM_URL)
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        _WAREHOUSE_TOKEN_SECRET,
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
        _WAREHOUSE_TOKEN_ENTRY_ID,
    )
    settings = GoogleFormsSettings()
    assert settings.technician_warehouse_inventory_form_url == _WAREHOUSE_FORM_URL
    assert (
        settings.technician_warehouse_inventory_form_token_secret.get_secret_value()
        == _WAREHOUSE_TOKEN_SECRET
    )
    assert settings.technician_warehouse_inventory_form_token_entry_id == _WAREHOUSE_TOKEN_ENTRY_ID
