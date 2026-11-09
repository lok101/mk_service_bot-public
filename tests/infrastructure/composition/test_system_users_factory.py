from __future__ import annotations

import pytest

from src.application.master_data import InMemorySystemUserStore
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.infrastructure.composition.factories import build_system_user_store


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


def test_factory_memory_without_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(mongodb=MongoSettings.model_construct(uri=None))
    store = build_system_user_store(settings, mongo_client=None)
    assert isinstance(store, InMemorySystemUserStore)


def test_factory_raises_when_mongo_configured_without_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/test")
    settings = Settings()
    assert settings.mongodb.is_configured is True
    with pytest.raises((ValueError, RuntimeError), match="(?i)mongo"):
        build_system_user_store(settings, mongo_client=None)
