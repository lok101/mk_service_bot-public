from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores, MachineKind
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _widget_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _signed_widget_fields(*, tg: int = _ADMIN_TG, auth_date: str | None = None) -> dict[str, str]:
    fields = {
        "id": str(tg),
        "auth_date": str(int(_FROZEN_NOW.timestamp())) if auth_date is None else auth_date,
    }
    fields["hash"] = _widget_hash(fields, _BOT_TOKEN)
    return fields


def _build_app(
    *,
    enabled: bool = True,
    with_master_stores: bool = False,
) -> tuple[FastAPI, AdminHttpDeps]:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            ["Id", "Имя", "Роль", "телеграм id", "Id техника", "is active"],
            ["u1", "Ops", "администратор", str(_ADMIN_TG), "", "да"],
        ],
    )
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
    master_stores = InMemoryMasterDataStores() if with_master_stores else None
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
        stub_login_enabled=False,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _FROZEN_NOW,
        master_stores=master_stores,
        users_enabled=False,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=enabled)
    return app, deps


def test_park_install_accepts_micro_market() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/install",
        data={
            "name": "Холодильник",
            "city": "Город",
            "street": "ул. 1",
            "house": "1",
            "kind": "micro_market",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    machines = deps.master_stores.machines.list_all()
    assert len(machines) == 1
    assert machines[0].kind is MachineKind.MICRO_MARKET
    assert machines[0].machine_id.value == "701"


def test_park_kind_filter_includes_micro_market() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/machines")
    assert response.status_code == 200
    assert b'value="micro_market"' in response.content
