from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.master_data import (
    CreateTechnician,
    ImportTechniciansFromSheets,
    InMemoryTechnicianStore,
    Technician,
    TechnicianValidationError,
)
from src.application.master_data.memory import (
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
)
from src.application.master_data.models import TECHNICIAN_COUNTER_KEY
from src.application.sheets import TechniciansDirectorySnapshot
from src.domain.ids import TechnicianId

_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
_ACTOR = 1


def _directory_snapshot() -> TechniciansDirectorySnapshot:
    return TechniciansDirectorySnapshot(
        names_by_id={
            TechnicianId("10003"): "Данил",
            TechnicianId("10017"): "Егор",
        },
    )


def test_import_preserves_ids() -> None:
    snapshot = _directory_snapshot()
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    result = ImportTechniciansFromSheets(store=store, counters=counters).execute(snapshot)
    assert result.imported == 2
    stored = store.get(TechnicianId("10003"))
    assert stored is not None
    assert stored.name == "Данил"
    assert stored.is_active is True
    other = store.get(TechnicianId("10017"))
    assert other is not None
    assert other.name == "Егор"
    assert other.is_active is True


def test_import_noop_when_store_not_empty() -> None:
    store = InMemoryTechnicianStore()
    store.upsert(Technician(TechnicianId("1"), "Existing", True))
    counters = InMemoryMasterDataCounterStore()
    snapshot = _directory_snapshot()
    result = ImportTechniciansFromSheets(store=store, counters=counters).execute(snapshot)
    assert result.imported == 0
    stored = store.get(TechnicianId("1"))
    assert stored is not None
    assert stored.name == "Existing"
    assert store.get(TechnicianId("10003")) is None


def test_import_sets_counter_max_plus_one() -> None:
    snapshot = _directory_snapshot()
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    ImportTechniciansFromSheets(store=store, counters=counters).execute(snapshot)
    tech = CreateTechnician(store=store, counters=counters, audit=audit).execute(
        name="New",
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    assert tech.technician_id.value == "10018"


def test_import_rejects_empty_snapshot() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    snapshot = TechniciansDirectorySnapshot(names_by_id={})
    with pytest.raises(TechnicianValidationError):
        ImportTechniciansFromSheets(store=store, counters=counters).execute(snapshot)
    assert store.is_empty()
    assert counters.get(TECHNICIAN_COUNTER_KEY) == 0
