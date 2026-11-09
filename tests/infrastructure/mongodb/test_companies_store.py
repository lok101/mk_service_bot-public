from __future__ import annotations

import mongomock
import pytest

from src.application.master_data import InMemoryCompanyStore
from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.infrastructure.composition.factories import build_company_store
from src.infrastructure.mongodb.companies import MongoCompanyStore


def _stub_required_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)


def test_mongo_companies_roundtrip() -> None:
    client = mongomock.MongoClient()
    db = client["test"]
    store = MongoCompanyStore(collection=db["master_companies"])
    store.ensure_indexes()
    store.upsert(
        MasterCompany(
            company_id=123,
            name="Орлов М.О.",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=123,
                    roles=(KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG),
                ),
            ),
        ),
    )
    loaded = store.get(123)
    assert loaded is not None
    assert loaded.name == "Орлов М.О."
    assert loaded.is_active is True
    assert loaded.platform_bindings[0].roles == (
        KitPlatformRole.SALES_POLL,
        KitPlatformRole.CATALOG,
    )
    all_rows = store.list_all()
    assert len(all_rows) == 1
    assert all_rows[0].company_id == 123


def test_factory_memory_without_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(mongodb=MongoSettings.model_construct(uri=None))
    store = build_company_store(settings, mongo_client=None)
    assert isinstance(store, InMemoryCompanyStore)
