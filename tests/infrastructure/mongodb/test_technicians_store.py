from __future__ import annotations

import mongomock
import pytest

from src.application.master_data import InMemoryTechnicianStore, Technician
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.domain.ids import TechnicianId
from src.infrastructure.composition.factories import build_technician_store
from src.infrastructure.mongodb.technicians import MongoTechnicianStore


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


def test_mongo_technicians_roundtrip() -> None:
    client = mongomock.MongoClient()
    db = client["test"]
    store = MongoTechnicianStore(collection=db["master_technicians"])
    store.ensure_indexes()
    store.upsert(
        Technician(
            technician_id=TechnicianId("10003"),
            name="Данил",
            is_active=True,
        ),
    )
    loaded = store.get(TechnicianId("10003"))
    assert loaded is not None
    assert loaded.name == "Данил"
    assert loaded.is_active is True
    all_rows = store.list_all()
    assert len(all_rows) == 1
    assert all_rows[0].technician_id == TechnicianId("10003")


def test_factory_memory_without_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(mongodb=MongoSettings.model_construct(uri=None))
    store = build_technician_store(settings, mongo_client=None)
    assert isinstance(store, InMemoryTechnicianStore)
