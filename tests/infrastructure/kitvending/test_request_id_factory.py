from __future__ import annotations

from pathlib import Path

import mongomock
import pytest
from pydantic import SecretStr

import src.infrastructure.mongodb.kitvending_request_ids as mongo_store_module
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.kitvending import KitVendingSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.mongodb import MongoSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.integrations import build_kitvending_request_id_store
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)
from src.infrastructure.mongodb.kitvending_request_ids import MongoKitVendingRequestIdStore


def _settings(
    tmp_path: Path,
    *,
    ingestion_enabled: bool = False,
    worker_enabled: bool = False,
    mongo_uri: str | None = None,
) -> Settings:
    accounts_path = tmp_path / "kit_platform_accounts.json"
    from tests.infrastructure.kitvending.platform_account_helpers import (
        platform_account_row,
        write_platform_accounts_file,
    )

    write_platform_accounts_file(
        accounts_path,
        platform_account_row(
            account_key="head",
            company_id=1,
            kit_company_id=1,
            login="head",
            password="p1",
            role="sales_poll",
        ),
    )
    return Settings.model_construct(
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
        kitvending=KitVendingSettings.model_construct(
            accounts_path=accounts_path,
            ingestion_enabled=ingestion_enabled,
        ),
        matrix_automation=MatrixAutomationSettings.model_construct(
            worker_enabled=worker_enabled,
        ),
        mongodb=MongoSettings.model_construct(uri=mongo_uri),
        service_calendar=ServiceCalendarSettings(display_timezone="Asia/Yekaterinburg"),
    )


def test_build_kitvending_request_id_store_uses_in_memory_when_flags_off(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    store = build_kitvending_request_id_store(settings, mongo_client=None)
    assert isinstance(store, InMemoryKitVendingRequestIdStore)


def test_build_kitvending_request_id_store_uses_mongo_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        tmp_path,
        ingestion_enabled=True,
        mongo_uri="mongodb://test",
    )
    client = mongomock.MongoClient()
    collection = client["mk_service_bot"]["kitvending_request_ids"]
    monkeypatch.setattr(
        mongo_store_module,
        "resolve_collection",
        lambda *args, **kwargs: collection,
    )
    store = build_kitvending_request_id_store(settings, mongo_client=client)
    assert isinstance(store, MongoKitVendingRequestIdStore)


def test_build_kitvending_request_id_store_uses_mongo_when_required_and_configured_without_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, ingestion_enabled=True, mongo_uri="mongodb://test")
    collection = mongomock.MongoClient()["mk_service_bot"]["kitvending_request_ids"]
    monkeypatch.setattr(
        mongo_store_module,
        "resolve_collection",
        lambda *args, **kwargs: collection,
    )
    store = build_kitvending_request_id_store(settings, mongo_client=None)
    assert isinstance(store, MongoKitVendingRequestIdStore)


def test_build_kitvending_request_id_store_uses_in_memory_when_flags_off_with_mongo_client(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, mongo_uri="mongodb://test")
    client = mongomock.MongoClient()
    store = build_kitvending_request_id_store(settings, mongo_client=client)
    assert isinstance(store, InMemoryKitVendingRequestIdStore)


def test_build_kitvending_request_id_store_fail_fast_ingestion_without_mongo(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, ingestion_enabled=True, mongo_uri=None)
    with pytest.raises(ValueError, match="KitVending RequestId store requires Mongo"):
        build_kitvending_request_id_store(settings, mongo_client=None)


def test_build_kitvending_request_id_store_fail_fast_worker_without_mongo(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, worker_enabled=True, mongo_uri=None)
    with pytest.raises(ValueError, match="KitVending RequestId store requires Mongo"):
        build_kitvending_request_id_store(settings, mongo_client=None)


def test_build_kitvending_request_id_store_no_fail_fast_when_accounts_missing(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, ingestion_enabled=True, mongo_uri=None)
    settings.kitvending.accounts_path = tmp_path / "missing.json"
    store = build_kitvending_request_id_store(settings, mongo_client=None)
    assert isinstance(store, InMemoryKitVendingRequestIdStore)
