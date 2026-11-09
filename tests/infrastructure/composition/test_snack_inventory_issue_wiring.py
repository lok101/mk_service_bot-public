from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.settings import Settings
from src.config.snack_loading import SnackLoadingSettings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.snack_inventory_forms import (
    build_issue_snack_inventory_link,
    build_snack_inventory_form_factory,
)
from src.infrastructure.google_forms.snack_inventory_forms import DriveSnackInventoryFormFactory


def _base_settings(
    *,
    user_oauth_credentials_file: str,
    snack: SnackLoadingSettings,
) -> Settings:
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("dev-bot-token-16chars"),
            webhook_public_host="",
        ),
        google_forms=GoogleFormsSettings.model_construct(
            webhook_secret=SecretStr("dev-webhook-secret"),
            revision_form_token_secret=SecretStr("dev-revision-form-token-secret"),
            loading_form_token_secret=SecretStr("dev-loading-form-token-secret"),
            revision_form_url="https://forms.example/revision",
            loading_form_url="https://forms.example/loading",
            revision_form_token_entry_id="entry.1",
            loading_form_token_entry_id="entry.2",
            technician_warehouse_inventory_form_url="https://forms.example/warehouse",
            technician_warehouse_inventory_form_token_secret=SecretStr(
                "dev-warehouse-inventory-form-token-secret",
            ),
            technician_warehouse_inventory_form_token_entry_id="entry.3",
            token_field_name="token",
            user_oauth_credentials_file=user_oauth_credentials_file,
            inventory_form_qty_max=30,
        ),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file="",
            product_catalog_spreadsheet_id="catalog-spreadsheet",
            product_catalog_sheet_id=1,
            coffee_technician_locations_spreadsheet_id="locations-spreadsheet",
            coffee_technician_locations_sheet_id=2,
            users_sheet_id=3,
        ),
        snack_loading=snack,
    )


def _snack_forms_configured() -> SnackLoadingSettings:
    return SnackLoadingSettings.model_construct(
        inventory_form_now_template_id="tpl-now",
        inventory_form_as_of_template_id="tpl-as-of",
        inventory_form_now_token_secret=SecretStr("now-secret"),
        inventory_form_as_of_token_secret=SecretStr("as-of-secret"),
        inventory_form_token_entry_id="entry.snack",
    )


def test_build_issue_snack_inventory_link_raises_when_forms_configured_without_oauth() -> None:
    settings = _base_settings(
        user_oauth_credentials_file="",
        snack=_snack_forms_configured(),
    )

    with pytest.raises(ValueError, match="GOOGLE_FORMS_USER_OAUTH_CREDENTIALS_FILE"):
        build_issue_snack_inventory_link(settings, client=None)


def test_build_issue_snack_inventory_link_none_when_forms_unconfigured() -> None:
    settings = _base_settings(
        user_oauth_credentials_file="",
        snack=SnackLoadingSettings.model_construct(),
    )

    assert build_issue_snack_inventory_link(settings, client=None) is None


def test_build_snack_inventory_form_factory_wires_set_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _base_settings(
        user_oauth_credentials_file="creds.json",
        snack=_snack_forms_configured(),
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.snack_inventory_forms"
        ".load_forms_user_oauth_credentials",
        lambda _path: object(),
    )

    def fake_build(service: str, version: str, **kwargs: Any) -> MagicMock:
        del version, kwargs
        client = MagicMock(name=service)
        if service == "forms":
            client.forms.return_value.setPublishSettings.return_value.execute.return_value = {
                "ok": True,
            }
        return client

    monkeypatch.setattr(
        "googleapiclient.discovery.build",
        fake_build,
    )

    factory = build_snack_inventory_form_factory(settings)

    assert isinstance(factory, DriveSnackInventoryFormFactory)
    assert factory.qty_max == 30
    assert callable(factory.forms_set_publish_settings)
    assert factory.forms_set_publish_settings(formId="f1", body={}) == {"ok": True}
