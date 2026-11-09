from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.application.master_data import (
    InMemoryCompanyStore,
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.master_data import MasterDataSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.admin_http_deps import build_admin_http_deps
from src.infrastructure.composition.runtime import ProcessRuntime
from src.infrastructure.composition.wiring.assemble import assemble_app_container


def test_admin_deps_wire_companies_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryCompanyStore()
    store.upsert(
        MasterCompany(
            company_id=7,
            name="Ромашка",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=7,
                    roles=(KitPlatformRole.CATALOG,),
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
            enabled=False,
            companies_enabled=True,
            session_secret=SecretStr("admin-session-secret-long-enough"),
            telegram_bot_username="testbot",
            dev_stub_login_enabled=True,
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
    assert deps.companies_enabled is True
    assert deps.company_store is not None
    assert deps.create_company is not None
    assert deps.update_company is not None
    assert isinstance(deps.company_display_names, dict)
    assert deps.company_display_names[7] == "Ромашка"
    assert deps.refresh_company_display_names is not None
    deps.company_display_names.clear()
    deps.refresh_company_display_names()
    assert deps.company_display_names[7] == "Ромашка"
