from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.google_forms import GoogleFormsSettings


def _set_required_google_forms_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_FORMS_WEBHOOK_SECRET", "wh")
    monkeypatch.setenv("REVISION_FORM_TOKEN_SECRET", "rev")
    monkeypatch.setenv("LOADING_FORM_TOKEN_SECRET", "load")
    monkeypatch.setenv("REVISION_FORM_URL", "https://forms.example/revision")
    monkeypatch.setenv("LOADING_FORM_URL", "https://forms.example/loading")
    monkeypatch.setenv("REVISION_FORM_TOKEN_ENTRY_ID", "entry.1")
    monkeypatch.setenv("LOADING_FORM_TOKEN_ENTRY_ID", "entry.2")
    monkeypatch.setenv("GOOGLE_FORM_TOKEN_FIELD_NAME", "token")
    monkeypatch.setenv("TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL", "https://forms.example/wh")
    monkeypatch.setenv("TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET", "wh-inv")
    monkeypatch.setenv("TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID", "entry.3")


def test_inventory_form_qty_max_defaults_to_99(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_google_forms_env(monkeypatch)
    monkeypatch.delenv("INVENTORY_FORM_QTY_MAX", raising=False)
    settings = GoogleFormsSettings()
    assert settings.inventory_form_qty_max == 99


def test_inventory_form_qty_max_reads_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_google_forms_env(monkeypatch)
    monkeypatch.setenv("INVENTORY_FORM_QTY_MAX", "45")
    settings = GoogleFormsSettings()
    assert settings.inventory_form_qty_max == 45


def test_inventory_form_qty_max_allows_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_google_forms_env(monkeypatch)
    monkeypatch.setenv("INVENTORY_FORM_QTY_MAX", "0")
    settings = GoogleFormsSettings()
    assert settings.inventory_form_qty_max == 0


def test_inventory_form_qty_max_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_google_forms_env(monkeypatch)
    monkeypatch.setenv("INVENTORY_FORM_QTY_MAX", "-1")
    with pytest.raises(ValidationError):
        GoogleFormsSettings()
