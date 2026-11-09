from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from src.application.product_identity.sync_procurement_mirror import SyncProcurementMirror
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.mongodb import MongoSettings
from src.config.moysklad import MoySkladSettings
from src.config.product_procurement_mirror import ProductProcurementMirrorSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.product_identity import (
    build_procurement_mirror_worker,
)
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)
from src.infrastructure.product_identity.memory_store import MemoryDomainProductStore
from src.infrastructure.product_identity.procurement_mirror_worker import (
    ProductProcurementMirrorSyncWorker,
)


def _base_settings() -> Settings:
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
        mongodb=MongoSettings.model_construct(uri=None),
    )


def test_build_procurement_mirror_worker_disabled_returns_none() -> None:
    settings = _base_settings().model_copy(
        update={
            "product_procurement_mirror": ProductProcurementMirrorSettings.model_construct(
                enabled=False,
                sync_interval_seconds=3600,
                supply_concurrency=5,
                collection="product_procurement_mirror",
            ),
        },
    )
    worker, store, sync, close = build_procurement_mirror_worker(
        settings,
        domain_product_store=MemoryDomainProductStore(),
        mongo_client=None,
    )
    assert worker is None
    assert store is None
    assert sync is None
    close()


def test_build_procurement_mirror_app_process_keeps_store_without_http() -> None:
    # happy: app (include_moysklad_http=False) still gets store for admin UI
    settings = _base_settings().model_copy(
        update={
            "product_procurement_mirror": ProductProcurementMirrorSettings.model_construct(
                enabled=True,
                sync_interval_seconds=3600,
                supply_concurrency=5,
                collection="product_procurement_mirror",
            ),
            "moysklad": MoySkladSettings.model_construct(
                api_token=SecretStr("token"),
                main_store_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            ),
        },
    )
    worker, store, sync, close = build_procurement_mirror_worker(
        settings,
        domain_product_store=MemoryDomainProductStore(),
        mongo_client=None,
        include_moysklad_http=False,
    )
    assert worker is None
    assert isinstance(store, MemoryProcurementMirrorStore)
    assert sync is None
    close()


def test_build_procurement_mirror_worker_enabled_returns_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    fake_client.close = MagicMock()
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.product_identity."
        "MoySkladPurchasePricesHttpClient.from_settings",
        lambda *_args, **_kwargs: fake_client,
    )
    settings = _base_settings().model_copy(
        update={
            "product_procurement_mirror": ProductProcurementMirrorSettings.model_construct(
                enabled=True,
                sync_interval_seconds=120,
                supply_concurrency=3,
                collection="product_procurement_mirror",
            ),
            "moysklad": MoySkladSettings.model_construct(
                api_token=SecretStr("token"),
                main_store_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            ),
        },
    )
    worker, store, sync, close = build_procurement_mirror_worker(
        settings,
        domain_product_store=MemoryDomainProductStore(),
        mongo_client=None,
    )
    assert isinstance(worker, ProductProcurementMirrorSyncWorker)
    assert isinstance(store, MemoryProcurementMirrorStore)
    assert isinstance(sync, SyncProcurementMirror)
    assert worker.interval_seconds == 120
    close()
    fake_client.close.assert_called_once()
