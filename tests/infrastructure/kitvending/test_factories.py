from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr
from tests.infrastructure.kitvending.platform_account_helpers import (
    platform_account_row,
    write_platform_accounts_file,
)

from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.kitvending import KitVendingSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories import (
    build_kitvending_client,
    build_matrix_deployer,
)
from src.infrastructure.integrations.kitvending.client import KitVendingHttpClient
from src.infrastructure.integrations.kitvending.not_configured_client import (
    NotConfiguredKitVendingClient,
)
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)
from src.infrastructure.kitvending.deploy.coordinator import BatchMatrixDeployCoordinator


def _settings_with_kit(
    *,
    accounts_path: Path,
    api_base_url: str = "https://kit.example/APIService.svc",
) -> Settings:
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
            api_base_url=api_base_url,
            requests_per_window=1,
            window_seconds=10.0,
            backoff_seconds=0.01,
        ),
        matrix_automation=MatrixAutomationSettings(),
        service_calendar=ServiceCalendarSettings(display_timezone="Asia/Yekaterinburg"),
    )


def test_build_matrix_deployer_returns_not_configured_empty_coordinator(tmp_path: Path) -> None:
    # Settings.model_construct still materializes default_factory nested settings;
    # stub required google/telegram fields like tests/infrastructure/composition/.
    settings = _settings_with_kit(accounts_path=tmp_path / "missing.json")
    deployer = build_matrix_deployer(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
        http_client=httpx.Client(),
    )
    assert isinstance(deployer, BatchMatrixDeployCoordinator)
    assert deployer.clients == ()
    assert deployer.display_timezone == ZoneInfo("Asia/Yekaterinburg")


def test_build_matrix_deployer_does_not_create_http_when_accounts_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[httpx.Client] = []
    real_client = httpx.Client

    def tracking_client(*args: object, **kwargs: object) -> httpx.Client:
        client = real_client(*args, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", tracking_client)
    settings = _settings_with_kit(accounts_path=tmp_path / "missing.json")
    deployer = build_matrix_deployer(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(deployer, BatchMatrixDeployCoordinator)
    assert deployer.clients == ()
    assert created == []


def test_build_matrix_deployer_builds_clients_from_accounts_json(tmp_path: Path) -> None:
    accounts_path = tmp_path / "accounts.json"
    write_platform_accounts_file(
        accounts_path,
        platform_account_row(
            account_key="head",
            company_id=1,
            login="head",
            password="p1",
            role="sales_poll",
        ),
        platform_account_row(
            account_key="child",
            company_id=2,
            kit_company_id=2,
            login="child",
            password="p2",
            role="catalog",
        ),
    )
    settings = _settings_with_kit(accounts_path=accounts_path)
    http = httpx.Client()
    store = InMemoryKitVendingRequestIdStore()
    try:
        deployer = build_matrix_deployer(
            settings,
            request_id_store=store,
            http_client=http,
        )
        assert isinstance(deployer, BatchMatrixDeployCoordinator)
        assert len(deployer.clients) == 2
        assert deployer.blocking_label == "БЛОК"
        assert deployer.display_timezone == ZoneInfo("Asia/Yekaterinburg")
        assert deployer.load_timeout_seconds == 300
        assert deployer.clients[0] is not deployer.clients[1]
        assert deployer.clients[0]._api._request_id_store is store
        assert deployer.clients[1]._api._request_id_store is store
    finally:
        http.close()


def test_build_kitvending_client_returns_not_configured_when_empty(tmp_path: Path) -> None:
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=tmp_path / "missing_accounts.json",
    )
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )

    assert isinstance(client, NotConfiguredKitVendingClient)


def test_build_kitvending_client_returns_not_configured_when_accounts_file_invalid(
    tmp_path: Path,
) -> None:
    accounts_path = tmp_path / "accounts.json"
    accounts_path.write_text("not-json", encoding="utf-8")
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=accounts_path,
    )
    assert settings.is_configured is True
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(client, NotConfiguredKitVendingClient)


def test_build_kitvending_client_uses_accounts_file(tmp_path: Path) -> None:
    accounts_path = tmp_path / "accounts.json"
    write_platform_accounts_file(
        accounts_path,
        platform_account_row(
            account_key="head",
            company_id=1,
            login="head",
            password="p1",
            role="sales_poll",
        ),
        platform_account_row(
            account_key="child",
            company_id=2,
            kit_company_id=2,
            login="child",
            password="p2",
            role="catalog",
        ),
    )
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=accounts_path,
    )
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(client, KitVendingHttpClient)
    assert client.main_api.account.login == "head"


def test_build_kitvending_client_uses_shared_request_id_store(tmp_path: Path) -> None:
    accounts_path = tmp_path / "accounts.json"
    write_platform_accounts_file(
        accounts_path,
        platform_account_row(account_key="a", company_id=1, login="a", role="sales_poll"),
        platform_account_row(
            account_key="b",
            company_id=2,
            kit_company_id=2,
            login="b",
            role="catalog",
        ),
    )
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=accounts_path,
    )
    store = InMemoryKitVendingRequestIdStore()

    client = build_kitvending_client(settings, request_id_store=store)

    assert isinstance(client, KitVendingHttpClient)
    assert client.main_api._request_id_store is store
    assert client.catalog_clients[0]._request_id_store is store


def test_build_kitvending_client_creates_separate_rate_limiters_per_account(
    tmp_path: Path,
) -> None:
    accounts_path = tmp_path / "accounts.json"
    write_platform_accounts_file(
        accounts_path,
        platform_account_row(account_key="a", company_id=1, login="a", role="sales_poll"),
        platform_account_row(
            account_key="b",
            company_id=2,
            kit_company_id=2,
            login="b",
            role="catalog",
        ),
    )
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=accounts_path,
    )
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(client, KitVendingHttpClient)
    assert client.main_api._rate_limiter is not client.catalog_clients[0]._rate_limiter


def test_kitvending_http_client_close_shuts_down_underlying_httpx_client(
    tmp_path: Path,
) -> None:
    accounts_path = tmp_path / "accounts.json"
    write_platform_accounts_file(
        accounts_path,
        platform_account_row(company_id=42, login="user", password="pass"),
    )
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=accounts_path,
    )
    http = httpx.Client()
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
        http_client=http,
    )
    assert isinstance(client, KitVendingHttpClient)

    client.close()
    assert http.is_closed
