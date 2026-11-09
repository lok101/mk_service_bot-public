from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
from src.application.micromarket_loading.issue_inventory_link import (
    IssuedMicromarketInventoryLink,
    IssueMicromarketInventoryLink,
)
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.micromarket_loading import MicromarketLoadingSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.domain.ids import TechnicianId
from src.infrastructure.composition.factories.micromarket_inventory_forms import (
    build_issue_micromarket_inventory_link,
    build_kit_product_groups_loader,
    build_micromarket_inventory_form_factory,
)
from src.infrastructure.google_forms.micromarket_inventory_forms import (
    DriveMicromarketInventoryFormFactory,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketInventoryFormRegistry,
    StubMicromarketInventoryFormFactory,
    StubMicromarketInventoryFormsConfig,
)

_CLOCK = lambda: datetime(2026, 10, 9, tzinfo=UTC)  # noqa: E731


def _base_settings(
    *,
    user_oauth_credentials_file: str,
    micromarket: MicromarketLoadingSettings,
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
        micromarket_loading=micromarket,
    )


def _micromarket_forms_configured() -> MicromarketLoadingSettings:
    return MicromarketLoadingSettings.model_construct(
        inventory_form_now_template_id="tpl-now",
        inventory_form_as_of_template_id="tpl-as-of",
        inventory_form_now_token_secret=SecretStr("now-secret"),
        inventory_form_as_of_token_secret=SecretStr("as-of-secret"),
        inventory_form_token_entry_id="entry.mm",
    )


def _micromarket_now_field_form_configured() -> MicromarketLoadingSettings:
    return MicromarketLoadingSettings.model_construct(
        field_forms_public_base_url="https://bot.example.com",
        inventory_form_now_token_secret=SecretStr("now-secret"),
    )


def test_build_issue_micromarket_inventory_link_raises_without_oauth() -> None:
    settings = _base_settings(
        user_oauth_credentials_file="",
        micromarket=_micromarket_forms_configured(),
    )

    with pytest.raises(ValueError, match="GOOGLE_FORMS_USER_OAUTH_CREDENTIALS_FILE"):
        build_issue_micromarket_inventory_link(settings, client=None)


def test_build_issue_now_field_form_without_oauth() -> None:
    """edge: Google OAuth off does not block now-only FieldForm issue."""
    settings = _base_settings(
        user_oauth_credentials_file="",
        micromarket=_micromarket_now_field_form_configured(),
    )
    issuer = build_issue_micromarket_inventory_link(settings, client=None)
    assert issuer is not None
    result = issuer.execute(
        machine_code="701",
        mode="now",
        pages=(InventoryFormPage(kit_group_id=10, product_codes=("d-1",), title="Холод"),),
        technician_id=TechnicianId("tech-1"),
    )
    assert isinstance(result, IssuedMicromarketInventoryLink)
    assert result.form_url.startswith(
        "https://bot.example.com/forms/micromarket-inventory/now?token="
    )
    assert "forms.gle" not in result.form_url
    assert "docs.google" not in result.form_url


def test_build_issue_micromarket_inventory_link_none_when_unconfigured() -> None:
    settings = _base_settings(
        user_oauth_credentials_file="",
        micromarket=MicromarketLoadingSettings.model_construct(),
    )

    assert build_issue_micromarket_inventory_link(settings, client=None) is None


def test_build_micromarket_inventory_form_factory_wires_set_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "creds.json"
    credentials.write_text("{}", encoding="utf-8")
    settings = _base_settings(
        user_oauth_credentials_file=str(credentials),
        micromarket=_micromarket_forms_configured(),
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.micromarket_inventory_forms"
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

    factory = build_micromarket_inventory_form_factory(settings)

    assert isinstance(factory, DriveMicromarketInventoryFormFactory)
    assert factory.qty_max == 30
    assert callable(factory.forms_set_publish_settings)
    assert factory.forms_set_publish_settings(formId="f1", body={}) == {"ok": True}


def test_kit_groups_loader_fallback_when_client_missing() -> None:
    """edge: Kit unavailable → empty groups; issue still succeeds with fallback titles."""
    loaded = build_kit_product_groups_loader(None)()
    assert loaded.error
    assert loaded.groups == ()
    issuer = IssueMicromarketInventoryLink(
        registry=InMemoryMicromarketInventoryFormRegistry(),
        factory=StubMicromarketInventoryFormFactory(),
        forms_settings=StubMicromarketInventoryFormsConfig(),
        field_forms_public_base_url="https://bot.example.com",
        now_template_id="tpl-now",
        as_of_template_id="tpl-as-of",
        token_entry_id="entry.mm",
        now_token_secret="now-secret",
        as_of_token_secret="as-of-secret",
        clock=_CLOCK,
        qty_max=30,
    )
    pages = (InventoryFormPage(kit_group_id=10, product_codes=("d-1",), title="группа 10"),)
    result = issuer.execute(
        machine_code="701",
        mode="as_of",
        pages=pages,
        technician_id=TechnicianId("tech-1"),
    )
    assert isinstance(result, IssuedMicromarketInventoryLink)


def test_issue_uses_group_name_page_title_on_factory() -> None:
    """happy: GroupName in page title reaches factory on fingerprint miss (as_of)."""
    captured: dict[str, object] = {}

    class _CapturingFactory(StubMicromarketInventoryFormFactory):
        def copy_template_and_build_questions(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return super().copy_template_and_build_questions(**kwargs)

    issuer = IssueMicromarketInventoryLink(
        registry=InMemoryMicromarketInventoryFormRegistry(),
        factory=_CapturingFactory(),
        forms_settings=StubMicromarketInventoryFormsConfig(),
        field_forms_public_base_url="https://bot.example.com",
        now_template_id="tpl-now",
        as_of_template_id="tpl-as-of",
        token_entry_id="entry.mm",
        now_token_secret="now-secret",
        as_of_token_secret="as-of-secret",
        clock=_CLOCK,
        qty_max=30,
    )
    pages = (InventoryFormPage(kit_group_id=10, product_codes=("d-1",), title="Холод"),)
    result = issuer.execute(
        machine_code="701",
        mode="as_of",
        pages=pages,
        technician_id=TechnicianId("tech-1"),
    )
    assert isinstance(result, IssuedMicromarketInventoryLink)
    assert captured["pages"] == pages
