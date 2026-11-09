from __future__ import annotations

from datetime import UTC, datetime

import mongomock
import pytest

from src.application.reference_data import (
    ReferenceDataProvider,
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    compute_content_hash,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.config.location_roster import LocationRosterSettings
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.composition.factories import build_location_roster_store
from src.infrastructure.composition.factories.location_roster import attach_location_roster
from src.infrastructure.mongodb.location_roster import MongoLocationRosterStore
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore

_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
_COFFEE = [
    ["Id локации", "Имя локации", "Имя техника", "Id техника", "Пн"],
    ["101", "Школа", "Иван", "001", "да"],
]


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
    store = build_location_roster_store(settings, client=None)
    assert isinstance(store, InMemoryLocationRosterStore)


def test_factory_mongo_when_uri_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    client = mongomock.MongoClient()
    settings = Settings(
        mongodb=MongoSettings.model_construct(uri="mongodb://localhost/test"),
        location_roster=LocationRosterSettings.model_construct(
            roster_collection="location_roster",
            audit_collection="location_roster_audit",
        ),
    )
    store = build_location_roster_store(settings, client=client)
    assert isinstance(store, MongoLocationRosterStore)


def test_attach_location_roster_imports_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    settings = Settings()
    roster = InMemoryLocationRosterStore()
    snapshots = InMemoryReferenceDataSnapshotStore()
    snapshots.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
            rows=tuple(tuple(cell for cell in row) for row in _COFFEE),
            content_hash=compute_content_hash(_COFFEE),
            last_fetched_at=_NOW,
            content_updated_at=_NOW,
        ),
    )
    provider = ReferenceDataProvider()
    attach_location_roster(
        provider,
        settings,
        roster_store=roster,
        snapshot_store=snapshots,
        now=_NOW,
    )
    entry = roster.get(MachineId("101"))
    assert entry is not None
    assert entry.technician_id == TechnicianId("001")


def test_attach_skips_import_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "false")
    settings = Settings()
    roster = InMemoryLocationRosterStore()
    snapshots = InMemoryReferenceDataSnapshotStore()
    snapshots.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
            rows=tuple(tuple(cell for cell in row) for row in _COFFEE),
            content_hash=compute_content_hash(_COFFEE),
            last_fetched_at=_NOW,
            content_updated_at=_NOW,
        ),
    )
    provider = ReferenceDataProvider()
    attach_location_roster(
        provider,
        settings,
        roster_store=roster,
        snapshot_store=snapshots,
        now=_NOW,
    )
    assert roster.get(MachineId("101")) is None
    assert roster.is_empty()
