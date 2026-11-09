from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pymongo.database import Database

from src.application.master_data import (
    CreateTechnician,
    ImportTechniciansFromSheets,
    UpdateTechnician,
    hydrate_technicians_directory,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.sheets import SystemUsersSnapshot, TechniciansDirectorySnapshot
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.infrastructure.mongodb.master_data import (
    MongoMasterDataAuditStore,
    MongoMasterDataCounterStore,
)
from src.infrastructure.mongodb.technicians import MongoTechnicianStore
from src.interfaces.admin.roster_view import build_roster_view_model

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
_ACTOR = 1
_IMPORTED_ID = TechnicianId("10003")
_IMPORTED_NAME = "Данил"
_OTHER_ID = TechnicianId("10017")
_OTHER_NAME = "Егор"
_NEW_NAME = "New"


def _import_snapshot() -> TechniciansDirectorySnapshot:
    return TechniciansDirectorySnapshot(
        names_by_id={
            _IMPORTED_ID: _IMPORTED_NAME,
            _OTHER_ID: _OTHER_NAME,
        },
    )


def _active_ids(store: MongoTechnicianStore) -> frozenset[TechnicianId]:
    return frozenset(
        technician.technician_id for technician in store.list_all() if technician.is_active
    )


def _provider_with_roster_catalog(
    store: MongoTechnicianStore,
    *,
    new_id: TechnicianId,
) -> ReferenceDataProvider:
    provider = ReferenceDataProvider()
    hydrate_technicians_directory(provider, store)
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Точка", _IMPORTED_NAME, _IMPORTED_ID.value],
        ],
    )
    provider.configure_roster(enabled=False, store=InMemoryLocationRosterStore())
    imported_user = SystemUser(
        user_id=SystemUserId("10"),
        name="A",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=10,
        technician_id=_IMPORTED_ID,
        company_roles=frozenset(),
    )
    new_user = SystemUser(
        user_id=SystemUserId("11"),
        name="B",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=11,
        technician_id=new_id,
        company_roles=frozenset(),
    )
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={10: imported_user, 11: new_user},
            users_by_technician_id={
                _IMPORTED_ID: imported_user,
                new_id: new_user,
            },
        ),
    )
    return provider


def test_import_create_deactivate_roster_picker(mongo_database: Database) -> None:
    store = MongoTechnicianStore(collection=mongo_database["master_technicians"])
    store.ensure_indexes()
    counters = MongoMasterDataCounterStore(collection=mongo_database["master_data_counters"])
    audit = MongoMasterDataAuditStore(collection=mongo_database["master_data_audit"])

    imported = ImportTechniciansFromSheets(store=store, counters=counters).execute(
        _import_snapshot(),
    )
    assert imported.imported == 2

    created = CreateTechnician(store=store, counters=counters, audit=audit).execute(
        name=_NEW_NAME,
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    assert created.name == _NEW_NAME
    assert created.is_active is True

    provider = ReferenceDataProvider()
    hydrate_technicians_directory(provider, store)
    names = provider.technicians_directory().names_by_id
    assert names[_IMPORTED_ID] == _IMPORTED_NAME
    assert names[_OTHER_ID] == _OTHER_NAME
    assert names[created.technician_id] == _NEW_NAME

    roster_provider = _provider_with_roster_catalog(store, new_id=created.technician_id)
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    before = build_roster_view_model(
        roster_provider,
        draft_store=draft,
        applied_store=applied,
        active_technician_ids=_active_ids(store),
    )
    before_ids = {option.id for option in before.technicians}
    assert created.technician_id.value in before_ids
    assert _IMPORTED_ID.value in before_ids

    UpdateTechnician(store=store, audit=audit).execute(
        technician_id=created.technician_id,
        name=None,
        is_active=False,
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )

    hydrate_technicians_directory(roster_provider, store)
    after = build_roster_view_model(
        roster_provider,
        draft_store=draft,
        applied_store=applied,
        active_technician_ids=_active_ids(store),
    )
    after_ids = {option.id for option in after.technicians}
    assert created.technician_id.value not in after_ids
    assert _IMPORTED_ID.value in after_ids
    assert roster_provider.technicians_directory().names_by_id[created.technician_id] == _NEW_NAME
