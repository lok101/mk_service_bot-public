from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.master_data import MasterDataSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.admin_http_deps import build_admin_http_deps
from src.infrastructure.composition.factories.company_directory import (
    build_company_display_names_map,
    build_kit_company_directory,
)
from src.infrastructure.composition.runtime import ProcessRuntime
from src.infrastructure.composition.wiring.assemble import assemble_app_container


def test_build_company_display_names_map_from_store() -> None:
    store = InMemoryCompanyStore()
    store.upsert(
        MasterCompany(
            company_id=123,
            name="Орлов М.О.",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=123,
                    roles=(KitPlatformRole.SALES_POLL,),
                ),
            ),
        ),
    )
    names = build_company_display_names_map(store)
    assert names[123] == "Орлов М.О."


def test_build_kit_company_directory_wraps_store() -> None:
    store = InMemoryCompanyStore()
    directory = build_kit_company_directory(store)
    assert directory.display_names() == {}


def test_admin_deps_company_names_from_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryCompanyStore()
    store.upsert(
        MasterCompany(
            company_id=123,
            name="Орлов М.О.",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=123,
                    roles=(KitPlatformRole.SALES_POLL,),
                ),
            ),
        ),
    )
    monkeypatch.setenv("BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("GOOGLE_FORMS_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("REVISION_FORM_TOKEN_SECRET", "test-revision-secret")
    monkeypatch.setenv("LOADING_FORM_TOKEN_SECRET", "test-loading-secret")
    monkeypatch.setenv("REVISION_FORM_URL", "https://forms.example/revision")
    monkeypatch.setenv("LOADING_FORM_URL", "https://forms.example/loading")
    monkeypatch.setenv("REVISION_FORM_TOKEN_ENTRY_ID", "entry.1")
    monkeypatch.setenv("LOADING_FORM_TOKEN_ENTRY_ID", "entry.2")
    monkeypatch.setenv("GOOGLE_FORM_TOKEN_FIELD_NAME", "token")
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL",
        "https://forms.example/warehouse",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        "test-warehouse-inventory-secret",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
        "entry.3",
    )
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)

    import src.infrastructure.composition.factories.admin_http_deps as admin_deps_mod

    monkeypatch.setattr(
        admin_deps_mod,
        "build_company_store",
        lambda settings, *, mongo_client=None: store,
    )

    settings = Settings.model_construct(
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
        ),
        master_data=MasterDataSettings.model_construct(
            enabled=True,
            session_secret=SecretStr("admin-session-secret-long-enough"),
            telegram_bot_username="testbot",
        ),
    )
    container = assemble_app_container(settings)
    from src.infrastructure.composition.container import AppContainer

    assert isinstance(container, AppContainer)
    runtime = ProcessRuntime(
        config=container.config,
        persistence=container.persistence,
        machine_ops=container.machine_ops,
        forms=container.forms,
        outbox=container.outbox,
        photos=container.photos,
        settlement=container.settlement,
        reference_data=container.reference_data,
        technician_warehouse=container.technician_warehouse,
        telegram=container.telegram,
    )
    deps = build_admin_http_deps(runtime, settings)
    assert deps.company_display_names is not None
    assert deps.company_display_names[123] == "Орлов М.О."


def test_assemble_export_uses_directory_display_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime

    from src.application.inventory_reconciliation import MachineCompanyOccupancy
    from src.application.master_data import (
        InMemoryMasterDataStores,
        InstallMachineAtLocation,
        InstallMachineAtLocationInput,
        MachineKind,
    )
    from src.infrastructure.testing.company_occupancy_fakes import (
        InMemoryMachineCompanyOccupancyStore,
    )

    captured_providers: list[object] = []
    map_called = False

    def fake_map(store: object) -> dict[int, str]:
        nonlocal map_called
        map_called = True
        del store
        return {123: "Орлов М.О."}

    import src.infrastructure.composition.wiring.assemble as assemble_mod

    original_hook = assemble_mod.build_master_data_export_hook

    def capture_hook(
        settings: Settings,
        *,
        roster_store: object,
        technician_names: dict[object, object],
        company_names_provider: object,
    ) -> object:
        captured_providers.append(company_names_provider)
        return original_hook(
            settings,
            roster_store=roster_store,
            technician_names=technician_names,
            company_names_provider=company_names_provider,
        )

    monkeypatch.setattr(assemble_mod, "build_company_display_names_map", fake_map)
    monkeypatch.setattr(assemble_mod, "build_master_data_export_hook", capture_hook)

    credentials = tmp_path / "creds.json"
    credentials.write_text("{}", encoding="utf-8")
    accounts = tmp_path / "accounts.json"
    accounts.write_text("[]", encoding="utf-8")

    monkeypatch.setenv("BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("GOOGLE_FORMS_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("REVISION_FORM_TOKEN_SECRET", "test-revision-secret")
    monkeypatch.setenv("LOADING_FORM_TOKEN_SECRET", "test-loading-secret")
    monkeypatch.setenv("REVISION_FORM_URL", "https://forms.example/revision")
    monkeypatch.setenv("LOADING_FORM_URL", "https://forms.example/loading")
    monkeypatch.setenv("REVISION_FORM_TOKEN_ENTRY_ID", "entry.1")
    monkeypatch.setenv("LOADING_FORM_TOKEN_ENTRY_ID", "entry.2")
    monkeypatch.setenv("GOOGLE_FORM_TOKEN_FIELD_NAME", "token")
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL",
        "https://forms.example/warehouse",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        "test-warehouse-inventory-secret",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
        "entry.3",
    )
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("MASTER_DATA_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "admin-session-secret-long-enough")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "testbot")
    monkeypatch.setenv("MASTER_DATA_SHEETS_EXPORT_ENABLED", "true")
    monkeypatch.setenv("MASTER_DATA_MIRROR_SPREADSHEET_ID", "mirror-book")
    monkeypatch.setenv("MASTER_DATA_MIRROR_LOCATIONS_SHEET_ID", "11")
    monkeypatch.setenv("MASTER_DATA_MIRROR_MACHINES_SHEET_ID", "12")
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("KITVENDING_ACCOUNTS_PATH", str(accounts))
    monkeypatch.delenv("MONGODB_URI", raising=False)

    settings = Settings()
    container = assemble_app_container(settings)

    assert map_called
    assert captured_providers
    provider = captured_providers[0]
    assert callable(provider)

    stores = container.reference_data.master_data_stores
    assert isinstance(stores, InMemoryMasterDataStores)
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    InstallMachineAtLocation(stores=stores, now_factory=lambda: now).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    mid = stores.machines.list_all()[0].machine_id
    occupancy_store = container.settlement.company_occupancy_store
    assert isinstance(occupancy_store, InMemoryMachineCompanyOccupancyStore)
    occupancy_store.replace_for_machine(
        mid,
        (MachineCompanyOccupancy(mid, 123, now, None),),
    )

    names = provider(stores)
    assert names[mid] == "Орлов М.О."
