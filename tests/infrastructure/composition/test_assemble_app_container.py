from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.micromarket_loading import MicromarketLoadingSettings
from src.config.settings import Settings
from src.config.snack_loading import SnackLoadingSettings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.wiring.assemble import assemble_app_container
from src.infrastructure.micromarket_loading.micromarket_sales_after import (
    MachineSalesMicromarketSalesAfter,
)


def _dev_settings_without_mongo() -> Settings:
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
        ),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file="credentials.json",
            product_catalog_spreadsheet_id="catalog-spreadsheet",
            product_catalog_sheet_id=1,
            coffee_technician_locations_spreadsheet_id="locations-spreadsheet",
            coffee_technician_locations_sheet_id=2,
            users_sheet_id=3,
        ),
    )


def test_assemble_app_container_without_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    container = assemble_app_container(_dev_settings_without_mongo())

    assert container.persistence.mongo_client is None
    assert container.machine_ops.repository is not None
    assert container.forms.accept_revision is not None
    assert container.outbox.worker is not None
    assert container.photos.batch_store is not None
    assert container.settlement.kitvending_client is not None
    assert container.config.bot_token


def test_app_container_does_not_validate_matrix_stock_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    settings = _dev_settings_without_mongo().model_copy(
        update={
            "matrix_automation": MatrixAutomationSettings.model_construct(
                substitution_guard_enabled=True,
                worker_enabled=False,
            ),
        },
    )
    container = assemble_app_container(settings)
    assert container.forms.accept_revision is not None
    assert container.outbox.worker is not None


def test_wire_forms_require_raises_when_snack_inventory_partially_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    settings = _dev_settings_without_mongo().model_copy(
        update={
            "snack_loading": SnackLoadingSettings.model_construct(
                inventory_form_now_token_secret=SecretStr("only-now-secret"),
            ),
        },
    )
    with pytest.raises(ValueError, match="SNACK_INVENTORY"):
        assemble_app_container(settings)


def test_wire_forms_sets_accept_snack_inventory_when_forms_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    settings = _dev_settings_without_mongo().model_copy(
        update={
            "snack_loading": SnackLoadingSettings.model_construct(
                inventory_form_now_template_id="tpl-now",
                inventory_form_as_of_template_id="tpl-as-of",
                inventory_form_now_token_secret=SecretStr("now-secret"),
                inventory_form_as_of_token_secret=SecretStr("as-of-secret"),
                inventory_form_token_entry_id="entry.snack",
            ),
        },
    )
    container = assemble_app_container(settings)
    deps = container.forms.webhook_deps
    assert deps.accept_snack_inventory is not None
    assert deps.snack_inventory_now_form_token_secret == "now-secret"
    assert deps.snack_inventory_as_of_form_token_secret == "as-of-secret"


def test_runtime_overrides_preserve_micromarket_inventory_webhook_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    settings = _dev_settings_without_mongo().model_copy(
        update={
            "micromarket_loading": MicromarketLoadingSettings.model_construct(
                inventory_form_now_template_id="tpl-now",
                inventory_form_as_of_template_id="tpl-as-of",
                inventory_form_now_token_secret=SecretStr("now-secret"),
                inventory_form_as_of_token_secret=SecretStr("as-of-secret"),
                inventory_form_token_entry_id="entry.micromarket",
            ),
        },
    )
    container = assemble_app_container(settings)
    wired = container.forms.webhook_deps

    runtime = container._runtime._webhook_deps_with_runtime_overrides()

    assert wired.accept_micromarket_inventory is not None
    assert wired.accept_micromarket_inventory.products is not None
    assert isinstance(
        wired.accept_micromarket_inventory.sales_after,
        MachineSalesMicromarketSalesAfter,
    )
    assert runtime.accept_micromarket_inventory is wired.accept_micromarket_inventory
    assert (
        runtime.micromarket_inventory_now_form_token_secret
        == wired.micromarket_inventory_now_form_token_secret
        == "now-secret"
    )
    assert (
        runtime.micromarket_inventory_as_of_form_token_secret
        == wired.micromarket_inventory_as_of_form_token_secret
        == "as-of-secret"
    )
    assert (
        runtime.verify_micromarket_inventory_form_token
        is wired.verify_micromarket_inventory_form_token
    )
