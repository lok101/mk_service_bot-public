from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.database import Database

from src.application.reference_data import (
    ImportLocationRosterFromSheets,
    LocationRosterEntry,
    ReferenceDataProvider,
    ReferenceDataSourceId,
)
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets.technician_locations import find_technician_id_for_machine_in_snapshot
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.mongodb.location_roster import MongoLocationRosterStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

pytestmark = pytest.mark.integration

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_TECH_TG = 2002
_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
_COFFEE_ROWS = (
    ("Id локации", "Имя локации", "Имя техника", "Id техника", "Пн"),
    ("101", "Школа", "Иван", "001", "да"),
)


def _widget_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _admin_rows(
    *,
    role: str = "администратор",
    active: str = "да",
    tg: int = _ADMIN_TG,
) -> list[list[str]]:
    return [
        ["Id", "Имя", "Роль", "телеграм id", "Id техника", "is active"],
        ["u1", "Ops", role, str(tg), "", active],
    ]


def _build_app(*, enabled: bool = True, stub: bool = False) -> tuple[FastAPI, AdminHttpDeps]:
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.BOT_USERS, _admin_rows())
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Школа", "Иван", "001"],
        ],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=enabled, store=roster_store)
    deps = AdminHttpDeps(
        provider=provider,
        roster_store=roster_store,
        roster_draft_store=InMemoryLocationRosterDraftStore(),
        visit_store=InMemoryServiceVisitStore(),
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        bot_token=_BOT_TOKEN,
        session_secret=_SESSION_SECRET,
        session_ttl_seconds=86400,
        telegram_auth_max_age_seconds=86400,
        telegram_bot_username="mk_bot",
        stub_login_enabled=stub,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _NOW,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=enabled)
    return app, deps


def test_import_then_overlay_reads_roster_not_sheet(mongo_database: Database) -> None:
    roster = MongoLocationRosterStore(
        roster_collection=mongo_database["location_roster"],
        audit_collection=mongo_database["location_roster_audit"],
    )
    ImportLocationRosterFromSheets(store=roster).execute(
        coffee_rows=[list(row) for row in _COFFEE_ROWS],
        snack_rows=None,
        catalog_machine_count=1,
        now=_NOW,
    )
    provider = ReferenceDataProvider()
    provider.configure_roster(enabled=True, store=roster)
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"], ["B", "Борис"]],
    )
    coffee_rows = [list(row) for row in _COFFEE_ROWS]
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, coffee_rows)
    after_import = provider.coffee_locations()
    assert find_technician_id_for_machine_in_snapshot(
        after_import,
        MachineId("101"),
    ) == TechnicianId("001")
    assert after_import.machines_by_technician_id[TechnicianId("001")][0].service_weekdays == (
        frozenset({0})
    )
    roster.save_batch(
        (
            LocationRosterEntry(
                machine_id=MachineId("101"),
                technician_id=TechnicianId("B"),
                service_weekdays=frozenset({1}),
                updated_at=_NOW,
                updated_by_telegram_user_id=1001,
            ),
        ),
        actor_telegram_user_id=1001,
        at=_NOW,
    )
    snapshot = provider.coffee_locations()
    assert find_technician_id_for_machine_in_snapshot(snapshot, MachineId("101")) == (
        TechnicianId("B")
    )
    assert snapshot.machines_by_technician_id[TechnicianId("B")][0].service_weekdays == (
        frozenset({1})
    )


def test_admin_auth_happy_signed_widget() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    fields = {"id": str(_ADMIN_TG), "auth_date": str(int(_NOW.timestamp()))}
    fields["hash"] = _widget_hash(fields, _BOT_TOKEN)
    login = client.post("/admin/auth/telegram", data=fields, follow_redirects=False)
    assert login.status_code in {302, 303}
    roster = client.get("/admin/roster")
    assert roster.status_code == 200
    assert "Школа" in roster.text


def test_admin_auth_fail_non_admin() -> None:
    app, deps = _build_app()
    deps.provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        _admin_rows(role="техник", tg=_TECH_TG),
    )
    client = TestClient(app)
    fields = {"id": str(_TECH_TG), "auth_date": str(int(_NOW.timestamp()))}
    fields["hash"] = _widget_hash(fields, _BOT_TOKEN)
    response = client.post("/admin/auth/telegram", data=fields)
    assert response.status_code == 403
    roster = client.get("/admin/roster", follow_redirects=False)
    assert roster.status_code in {302, 303}
