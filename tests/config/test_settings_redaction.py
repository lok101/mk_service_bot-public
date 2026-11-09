from __future__ import annotations

from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings


def _google_forms_settings() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
        webhook_secret=SecretStr("prod-webhook-secret-ok"),
        revision_form_token_secret=SecretStr("prod-revision-secret-ok"),
        loading_form_token_secret=SecretStr("prod-loading-secret-ok"),
        revision_form_url="https://forms.example/revision",
        loading_form_url="https://forms.example/loading",
        revision_form_token_entry_id="entry.1",
        loading_form_token_entry_id="entry.2",
        technician_warehouse_inventory_form_url="https://forms.example/warehouse",
        technician_warehouse_inventory_form_token_secret=SecretStr(
            "prod-warehouse-inventory-secret-ok",
        ),
        technician_warehouse_inventory_form_token_entry_id="entry.3",
        token_field_name="token",
    )


def test_secret_str_redacted_in_settings_repr() -> None:
    settings = Settings.model_construct(
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("super-secret-token-value"),
        ),
        google_forms=_google_forms_settings(),
    )
    text = repr(settings)
    assert "super-secret-token-value" not in text
    assert "**********" in text or "SecretStr" in text
