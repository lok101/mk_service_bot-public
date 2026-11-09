from __future__ import annotations

from pydantic import SecretStr

from src.application.master_data import InMemoryMasterDataStores
from src.application.micromarket_loading import ApplyMicromarketSaleToStock
from src.config.google_forms import GoogleFormsSettings
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.micromarket_loading import (
    build_apply_micromarket_sale_to_stock,
    build_micromarket_device_stock_store,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
)


def _settings_without_mongo() -> Settings:
    return Settings.model_construct(
        mongodb=MongoSettings.model_construct(uri=None),
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
    )


def test_build_micromarket_stock_store_memory_when_mongo_unconfigured() -> None:
    store = build_micromarket_device_stock_store(_settings_without_mongo(), client=None)
    assert isinstance(store, InMemoryMicromarketDeviceStockStore)


def test_build_apply_micromarket_sale_wiring_smoke() -> None:
    stores = InMemoryMasterDataStores()
    uc = build_apply_micromarket_sale_to_stock(
        _settings_without_mongo(),
        machine_store=stores.machines,
        client=None,
    )
    assert isinstance(uc, ApplyMicromarketSaleToStock)
