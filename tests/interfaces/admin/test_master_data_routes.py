from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores, MasterLocation
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster import LocationRosterEntry
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import (
    SystemUsersSnapshot,
    TechnicianLocationsSnapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import BotRole, CompanyRole, SystemUser, SystemUserId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_TECH_TG = 2002
_FROZEN_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_LEGACY_DISPLAY = "МЦ Здоровая семья | Фучика, 3"


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


def _build_app(
    *,
    enabled: bool = True,
    stub: bool = False,
    users_enabled: bool = False,
    with_master_stores: bool = False,
) -> tuple[FastAPI, AdminHttpDeps]:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            *_admin_rows(),
            ["u2", "Иван", "техник", "3003", "001", "да"],
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
        stub_login_enabled=stub,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _FROZEN_NOW,
        master_stores=master_stores,
        users_enabled=users_enabled,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=enabled)
    return app, deps


def test_admin_master_routes_404_when_disabled() -> None:
    app, _deps = _build_app(enabled=False, with_master_stores=True)
    client = TestClient(app)
    assert client.get("/admin/machines").status_code == 404


def test_admin_enabled_when_master_data_on() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    response = client.get("/admin/machines", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/admin/login" in response.headers["location"]


def test_nav_hides_park_when_master_stores_absent() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=False)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/roster")
    assert response.status_code == 200
    assert 'href="/admin/machines"' not in response.text
    assert 'href="/admin/roster"' in response.text


def test_nav_shows_park_when_master_enabled() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/machines")
    assert response.status_code == 200
    assert 'href="/admin/machines"' in response.text


def test_install_post_rejects_non_admin() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    deps.provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        _admin_rows(role="техник", tg=_TECH_TG),
    )
    client = TestClient(app)
    # Login rejects non-admin; plant session to assert POST panel gate.
    token = pack_admin_session(
        telegram_user_id=_TECH_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    response = client.post(
        "/admin/machines/install",
        data={
            "name": "A",
            "city": "Город",
            "street": "ul",
            "house": "1",
            "kind": "coffee",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 403
    assert deps.master_stores.machines.is_empty() is True


def test_machines_install_rejects_foreign_origin() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/install",
        data={
            "name": "A",
            "city": "Город",
            "street": "ul",
            "house": "1",
            "kind": "coffee",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert deps.master_stores is not None
    assert deps.master_stores.machines.is_empty() is True


def test_install_post_happy() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/install",
        data={
            "name": "Кафе",
            "city": "Город",
            "street": "ул. 1",
            "house": "1",
            "kind": "coffee",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert len(deps.master_stores.machines.list_all()) == 1
    location = deps.master_stores.locations.list_all()[0]
    assert location.name == "Кафе"
    assert location.city == "Город"
    assert location.street == "ул. 1"
    assert location.house == "1"
    assert location.display_name == "Кафе | ул. 1, 1"


def test_location_edit_requires_address_parts() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    deps.master_stores.locations.upsert(
        MasterLocation(
            location_id="legacy-1",
            name="",
            city="",
            street="",
            house="",
            display_name=_LEGACY_DISPLAY,
            latitude=None,
            longitude=None,
        )
    )
    before = deps.master_stores.locations.get("legacy-1")
    assert before is not None
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/locations/legacy-1",
        data={
            "name": "",
            "city": "",
            "street": "",
            "house": "",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "admin-error" in response.text
    after = deps.master_stores.locations.get("legacy-1")
    assert after == before


def test_location_edit_shows_legacy_display_hint() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    deps.master_stores.locations.upsert(
        MasterLocation(
            location_id="legacy-2",
            name="",
            city="",
            street="",
            house="",
            display_name=_LEGACY_DISPLAY,
            latitude=None,
            longitude=None,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/locations/legacy-2").text
    assert "Текущее имя:" in html
    assert _LEGACY_DISPLAY in html


def test_install_post_hydrates_provider_catalog() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    # Clear seeded coffee catalog so before_ids is empty (counter still starts at 101).
    deps.provider.apply_master_snapshots(
        coffee=TechnicianLocationsSnapshot(
            machines_by_technician_id={},
            technician_names_by_id={},
            unassigned_machines=(),
        ),
        snack=None,
        locations_directory=None,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    before_ids = {
        m.id.value for m in list_all_machines_from_snapshot(deps.provider.locations_catalog())
    }
    assert before_ids == set()
    response = client.post(
        "/admin/machines/install",
        data={
            "name": "Кафе Hydrate",
            "city": "Город",
            "street": "ул. 1",
            "house": "1",
            "kind": "coffee",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    machines = list_all_machines_from_snapshot(deps.provider.locations_catalog())
    after_ids = {m.id.value for m in machines}
    assert after_ids - before_ids, "provider catalog must gain installed machine"
    store_ids = {m.machine_id.value for m in deps.master_stores.machines.list_all()}
    assert store_ids <= after_ids


def test_relocate_post_happy() -> None:
    from src.application.master_data import (
        InstallMachineAtLocation,
        InstallMachineAtLocationInput,
        MachineKind,
    )

    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    installed = InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=lambda: now,
    ).execute(
        InstallMachineAtLocationInput(
            name="Старая",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        f"/admin/machines/{installed.machine_id.value}/relocate",
        data={
            "name": "Новая",
            "city": "Город",
            "street": "b",
            "house": "1",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert len(deps.master_stores.locations.list_all()) == 2
    open_p = deps.master_stores.placements.get_open(installed.machine_id)
    assert open_p is not None
    assert open_p.location_id != installed.location_id


def _install_coffee_for_relocate(deps: AdminHttpDeps) -> MachineId:
    from src.application.master_data import (
        InstallMachineAtLocation,
        InstallMachineAtLocationInput,
        MachineKind,
    )

    assert deps.master_stores is not None
    installed = InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=deps.now_factory,
    ).execute(
        InstallMachineAtLocationInput(
            name="Старая",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    return installed.machine_id


def _seed_roster_assignment(
    deps: AdminHttpDeps,
    machine_id: MachineId,
    *,
    technician_id: TechnicianId | None,
    weekdays: frozenset[int],
) -> LocationRosterEntry:
    entry = LocationRosterEntry(
        machine_id=machine_id,
        technician_id=technician_id,
        service_weekdays=weekdays,
        updated_at=deps.now_factory(),
        updated_by_telegram_user_id=_ADMIN_TG,
    )
    deps.roster_store.save_batch(
        (entry,),
        actor_telegram_user_id=_ADMIN_TG,
        at=deps.now_factory(),
    )
    deps.roster_draft_store.replace_all((entry,))
    return entry


def test_relocate_post_clears_technician_keeps_weekdays() -> None:
    # happy: успешная релокация снимает техника, дни ТО не трогает
    app, deps = _build_app(enabled=True, with_master_stores=True)
    machine_id = _install_coffee_for_relocate(deps)
    weekdays = frozenset({1, 3})
    _seed_roster_assignment(
        deps,
        machine_id,
        technician_id=TechnicianId("001"),
        weekdays=weekdays,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        f"/admin/machines/{machine_id.value}/relocate",
        data={
            "name": "Новая",
            "city": "Город",
            "street": "b",
            "house": "1",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    applied = deps.roster_store.get(machine_id)
    draft = deps.roster_draft_store.get(machine_id)
    assert applied is not None
    assert draft is not None
    assert applied.technician_id is None
    assert draft.technician_id is None
    assert applied.service_weekdays == weekdays
    assert draft.service_weekdays == weekdays


def test_relocate_post_already_unassigned_stays() -> None:
    # edge: уже без техника — assignment и дни не переписываются
    app, deps = _build_app(enabled=True, with_master_stores=True)
    machine_id = _install_coffee_for_relocate(deps)
    weekdays = frozenset({2})
    before = _seed_roster_assignment(
        deps,
        machine_id,
        technician_id=None,
        weekdays=weekdays,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        f"/admin/machines/{machine_id.value}/relocate",
        data={
            "name": "Новая",
            "city": "Город",
            "street": "b",
            "house": "1",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    applied = deps.roster_store.get(machine_id)
    draft = deps.roster_draft_store.get(machine_id)
    assert applied is not None
    assert draft is not None
    assert applied.technician_id is None
    assert draft.technician_id is None
    assert applied.service_weekdays == weekdays
    assert draft.service_weekdays == weekdays
    assert applied.updated_at == before.updated_at
    assert draft.updated_at == before.updated_at


def test_relocate_post_failed_does_not_clear_technician() -> None:
    # error: отказ релокации не снимает техника
    app, deps = _build_app(enabled=True, with_master_stores=True)
    machine_id = _install_coffee_for_relocate(deps)
    weekdays = frozenset({0, 4})
    _seed_roster_assignment(
        deps,
        machine_id,
        technician_id=TechnicianId("001"),
        weekdays=weekdays,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        f"/admin/machines/{machine_id.value}/relocate",
        data={
            "name": "",
            "city": "Город",
            "street": "b",
            "house": "1",
            "latitude": "",
            "longitude": "",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    applied = deps.roster_store.get(machine_id)
    draft = deps.roster_draft_store.get(machine_id)
    assert applied is not None
    assert draft is not None
    assert applied.technician_id == TechnicianId("001")
    assert draft.technician_id == TechnicianId("001")
    assert applied.service_weekdays == weekdays
    assert draft.service_weekdays == weekdays


def test_roster_post_still_works_with_master_enabled() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.get("/admin/roster")
    draft = deps.roster_draft_store.get(MachineId("101"))
    assert draft is not None
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset({2}),
            updated_at=deps.now_factory(),
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=draft.updated_at,
    )
    updated = deps.roster_draft_store.get(MachineId("101"))
    assert updated is not None
    response = client.post(
        "/admin/roster/apply",
        data={
            "technician-101": "001",
            "wd-101-2": "on",
            "expected_draft_updated_at-101": updated.updated_at.isoformat(),
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/roster"
    entry = deps.roster_store.get(MachineId("101"))
    assert entry is not None
    assert entry.technician_id == TechnicianId("001")
    assert 2 in entry.service_weekdays


def test_master_data_forbidden_without_panel_when_users_enabled() -> None:
    """error: flag on + settlement only → /admin/machines 403."""
    app, deps = _build_app(stub=True, users_enabled=True, with_master_stores=True)
    snap = SystemUsersSnapshot(
        users_by_telegram_id={
            _ADMIN_TG: SystemUser(
                user_id=SystemUserId("1"),
                name="Ops",
                role=BotRole.NONE,
                is_active=True,
                telegram_user_id=_ADMIN_TG,
                technician_id=None,
                company_roles=frozenset({CompanyRole.SETTLEMENT_OPERATOR}),
            ),
        },
        users_by_technician_id={},
    )
    deps.provider.apply_system_users_snapshot(snap)
    client = TestClient(app)
    # Settlement nav may be unmounted; plant session to assert MASTER_DATA gate.
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    assert client.get("/admin/machines").status_code == 403
