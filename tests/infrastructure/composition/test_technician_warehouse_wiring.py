from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import mongomock
import pytest
from aiogram import Bot
from pydantic import SecretStr

from src.application.machine_operations.ports import WarehouseInventoryFormUnconfigured
from src.application.outbox.handler_ids import TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID
from src.application.technician_warehouse import TechnicianWarehouseImportBlocked
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.config.technician_warehouse import TechnicianWarehouseSettings
from src.config.telegram import TelegramSettings
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted
from src.infrastructure.composition.factories.technician_warehouse import (
    build_technician_warehouse_inventory_link_provider,
    build_technician_warehouse_repository,
)
from src.infrastructure.composition.wiring.assemble import assemble_app_container
from src.infrastructure.integrations.google.forms.link_providers import (
    GoogleFormsTechnicianWarehouseInventoryLinkProvider,
    UnconfiguredTechnicianWarehouseInventoryLinkProvider,
)
from src.infrastructure.mongodb.technician_warehouse import MongoTechnicianWarehouseRepository
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseRepository,
)
from src.interfaces.google_forms.webhook import NoOpDirectWarehouseChatNotifier
from src.interfaces.telegram.direct_warehouse_chat_notifier import (
    TelegramDirectWarehouseChatNotifier,
)

_ANCHOR = datetime(2026, 5, 25, tzinfo=UTC)


def _settings(
    *,
    mongodb_uri: str | None = "mongodb://example",
    supply_store_codes: tuple[str, ...] = ("main",),
    warehouse_form_url: str = "https://forms.example/warehouse",
) -> Settings:
    return Settings.model_construct(
        environment="dev",
        mongodb=MongoSettings.model_construct(uri=mongodb_uri),
        technician_warehouse=TechnicianWarehouseSettings.model_construct(
            supply_store_codes=supply_store_codes,
        ),
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
            technician_warehouse_inventory_form_url=warehouse_form_url,
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


def _assemble_minimal(**overrides: object) -> object:
    settings = _settings(mongodb_uri=None, **overrides)
    return assemble_app_container(settings)


def test_factory_builds_mongo_repository_when_mongodb_configured() -> None:
    settings = _settings(mongodb_uri="mongodb://example")
    repository, event_store = build_technician_warehouse_repository(
        settings,
        client=mongomock.MongoClient(),
    )
    assert isinstance(repository, MongoTechnicianWarehouseRepository)
    assert event_store is repository.event_store


def test_factory_builds_in_memory_repository_without_mongodb() -> None:
    repository, event_store = build_technician_warehouse_repository(
        _settings(mongodb_uri=None),
    )
    assert isinstance(repository, InMemoryTechnicianWarehouseRepository)
    assert event_store is repository.event_store


def test_link_provider_factory_uses_warehouse_inventory_form_settings() -> None:
    google_forms = _settings(mongodb_uri=None).google_forms
    provider = build_technician_warehouse_inventory_link_provider(google_forms)
    assert isinstance(provider, GoogleFormsTechnicianWarehouseInventoryLinkProvider)
    assert provider.form_url == google_forms.technician_warehouse_inventory_form_url
    assert (
        provider.token_entry_id == google_forms.technician_warehouse_inventory_form_token_entry_id
    )
    assert provider.token_secret == (
        google_forms.technician_warehouse_inventory_form_token_secret.get_secret_value()
    )
    assert provider.form_url != google_forms.revision_form_url
    assert provider.token_entry_id != google_forms.revision_form_token_entry_id
    assert provider.token_secret != (google_forms.revision_form_token_secret.get_secret_value())


def test_link_provider_factory_unconfigured_when_warehouse_form_url_empty() -> None:
    google_forms = _settings(mongodb_uri=None, warehouse_form_url="").google_forms
    provider = build_technician_warehouse_inventory_link_provider(google_forms)
    assert isinstance(provider, UnconfiguredTechnicianWarehouseInventoryLinkProvider)
    with pytest.raises(WarehouseInventoryFormUnconfigured):
        provider.create_link(TechnicianId("tech-1"))


def test_assemble_succeeds_with_empty_warehouse_form_url() -> None:
    container = assemble_app_container(_settings(mongodb_uri=None, warehouse_form_url=""))
    assert isinstance(
        container.technician_warehouse.link_provider,
        UnconfiguredTechnicianWarehouseInventoryLinkProvider,
    )


def test_assemble_succeeds_with_empty_supply_codes() -> None:
    container = assemble_app_container(_settings(supply_store_codes=(), mongodb_uri=None))
    assert container.technician_warehouse is not None


def test_delta_call_not_assemble_blocks_when_supply_codes_empty() -> None:
    container = assemble_app_container(_settings(supply_store_codes=(), mongodb_uri=None))
    with pytest.raises(TechnicianWarehouseImportBlocked, match="SUPPLY_STORE_CODES"):
        asyncio.run(
            container.technician_warehouse.delta_port.get_delta(
                TechnicianId("tech-1"),
                after=None,
                until=_ANCHOR,
            ),
        )


def test_webhook_and_my_stock_use_same_warehouse_bundle_dependencies() -> None:
    container = _assemble_minimal()
    assert (
        container.forms.webhook_deps.accept_technician_warehouse_inventory
        is container.technician_warehouse.accept_inventory
    )
    assert (
        container.telegram.machine_dialog_deps.technician_warehouse_inventory_link_provider
        is container.technician_warehouse.link_provider
    )


def test_inventory_counted_has_warehouse_telegram_handler_after_bot_registration() -> None:
    container = _assemble_minimal()
    container._runtime.register_telegram(Bot(token="1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"))
    assert (
        TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID
        in container._runtime.publisher.handler_ids_for(TechnicianWarehouseInventoryCounted)
    )


def test_assemble_wires_publisher_into_warehouse_executor() -> None:
    container = _assemble_minimal()
    assert container.technician_warehouse.executor.publisher is container._runtime.publisher


def test_webhook_deps_keep_noop_warehouse_chat_without_bot() -> None:
    container = _assemble_minimal()
    deps = container._runtime._webhook_deps_with_runtime_overrides()
    assert isinstance(deps.direct_warehouse_chat_notifier, NoOpDirectWarehouseChatNotifier)


def test_webhook_deps_use_real_warehouse_chat_notifier_after_register_telegram() -> None:
    container = _assemble_minimal()
    container._runtime.register_telegram(
        Bot(token="1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"),
    )
    deps = container._runtime._webhook_deps_with_runtime_overrides()
    assert isinstance(
        deps.direct_warehouse_chat_notifier,
        TelegramDirectWarehouseChatNotifier,
    )
