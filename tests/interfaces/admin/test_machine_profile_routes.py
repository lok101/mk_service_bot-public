from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.inventory_reconciliation import (
    MachineCompanyOccupancy,
    MachineCompanyOccupancyStore,
)
from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.ids import MachineId
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_TECH_TG = 2002
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
    with_master_stores: bool = False,
    company_occupancy_store: MachineCompanyOccupancyStore | None = None,
    company_display_names: dict[int, str] | None = None,
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
        company_occupancy_store=company_occupancy_store,
        company_display_names=company_display_names,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=enabled)
    return app, deps


def _seed_machine(deps: AdminHttpDeps, *, kind: MachineKind = MachineKind.COFFEE) -> MachineId:
    assert deps.master_stores is not None
    InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=lambda: _FROZEN_NOW,
    ).execute(
        InstallMachineAtLocationInput(
            name="Школа",
            city="Город",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=kind,
            actor_telegram_user_id=_ADMIN_TG,
        )
    )
    machines = [m for m in deps.master_stores.machines.list_all() if m.kind is kind]
    assert machines
    return machines[-1].machine_id


def test_machine_profile_get_shows_checkboxes() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get(f"/admin/machines/{machine_id.value}")
    assert response.status_code == 200
    assert 'name="include_in_no_sales_monitoring"' in response.text
    assert 'name="create_visit_on_no_sales"' in response.text
    assert "checked" in response.text


def test_machine_profile_shows_company_name() -> None:
    occupancy = InMemoryMachineCompanyOccupancyStore()
    app, deps = _build_app(
        with_master_stores=True,
        company_occupancy_store=occupancy,
        company_display_names={7: "Орлов М.О."},
    )
    machine_id = _seed_machine(deps)
    occupancy.replace_for_machine(
        machine_id,
        (MachineCompanyOccupancy(machine_id, 7, _FROZEN_NOW, None),),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get(f"/admin/machines/{machine_id.value}").text
    assert "Орлов М.О." in html
    assert 'name="company"' not in html


def test_machine_profile_post_ignores_company_field() -> None:
    occupancy = InMemoryMachineCompanyOccupancyStore()
    app, deps = _build_app(
        with_master_stores=True,
        company_occupancy_store=occupancy,
        company_display_names={7: "Орлов М.О."},
    )
    machine_id = _seed_machine(deps)
    occupancy.replace_for_machine(
        machine_id,
        (MachineCompanyOccupancy(machine_id, 7, _FROZEN_NOW, None),),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.post(
        f"/admin/machines/{machine_id.value}",
        data={
            "include_in_no_sales_monitoring": "on",
            "company": "Evil Corp",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    html = client.get(f"/admin/machines/{machine_id.value}").text
    assert "Орлов М.О." in html
    assert "Evil Corp" not in html
    intervals = occupancy.list_for_machine(machine_id)
    assert len(intervals) == 1
    assert intervals[0].company_id == 7


def test_machine_profile_has_admin_save_bar() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get(f"/admin/machines/{machine_id.value}")
    assert response.status_code == 200
    assert "admin-save-bar" in response.text


def test_machine_profile_post_persists_flags() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        f"/admin/machines/{machine_id.value}",
        data={},  # unchecked → False
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert deps.master_stores is not None
    saved = deps.master_stores.machines.get(machine_id)
    assert saved is not None
    assert saved.include_in_no_sales_monitoring is False
    assert saved.create_visit_on_no_sales is False


def test_machine_profile_post_persists_checked_flags() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps)
    assert deps.master_stores is not None
    # Start from off so POST on → True is observable.
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.post(
        f"/admin/machines/{machine_id.value}",
        data={},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    response = client.post(
        f"/admin/machines/{machine_id.value}",
        data={
            "include_in_no_sales_monitoring": "on",
            "create_visit_on_no_sales": "on",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = deps.master_stores.machines.get(machine_id)
    assert saved is not None
    assert saved.include_in_no_sales_monitoring is True
    assert saved.create_visit_on_no_sales is True


def test_machine_profile_404_unknown() -> None:
    app, _deps = _build_app(with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    assert client.get("/admin/machines/999999").status_code == 404


def test_machine_profile_404_when_master_disabled() -> None:
    app, _deps = _build_app(enabled=False, with_master_stores=True)
    client = TestClient(app)
    assert client.get("/admin/machines/101").status_code == 404


def test_machine_profile_403_without_panel() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps)
    deps.provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        _admin_rows(role="техник", tg=_TECH_TG),
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_TECH_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    assert client.get(f"/admin/machines/{machine_id.value}").status_code == 403


def test_roster_location_name_links_profile_when_master_on() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert f'href="/admin/machines/{machine_id.value}"' in html


def test_park_machine_links_profile() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert f'href="/admin/machines/{machine_id.value}"' in html


def test_roster_no_profile_link_when_master_off() -> None:
    app, _deps = _build_app(with_master_stores=False)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert 'href="/admin/machines/' not in html
    assert "Школа" in html


def test_install_not_captured_by_profile() -> None:
    app, _deps = _build_app(with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/machines/install")
    assert response.status_code == 200
    assert "master-install-form" in response.text
    assert "machine_profile" not in response.text
    assert 'name="include_in_no_sales_monitoring"' not in response.text


def test_coffee_profile_shows_monitoring_and_equipment_tabs() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps, kind=MachineKind.COFFEE)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get(f"/admin/machines/{machine_id.value}").text
    assert "admin-workspace-tabs" in html
    assert 'data-tab="monitoring"' in html
    assert 'data-tab="equipment"' in html
    assert "Мониторинг" in html
    assert "Оборудование" in html
    assert 'name="include_in_visit_photo_review"' in html
    assert 'name="include_in_no_sales_monitoring"' in html
    assert 'name="create_visit_on_no_sales"' in html
    assert 'name="coffee_machine_model_id"' in html


def test_coffee_profile_monitoring_tab_hides_equipment_panel() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps, kind=MachineKind.COFFEE)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get(f"/admin/machines/{machine_id.value}?tab=monitoring").text
    assert 'class="admin-workspace-panel" data-tab="equipment" hidden' in html
    assert 'class="admin-workspace-panel" data-tab="monitoring"' in html
    assert 'data-tab="monitoring" hidden' not in html


def test_coffee_profile_equipment_tab_shows_model_selects() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps, kind=MachineKind.COFFEE)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get(f"/admin/machines/{machine_id.value}?tab=equipment").text
    assert 'class="admin-workspace-panel" data-tab="monitoring" hidden' in html
    assert 'name="coffee_machine_model_id"' in html
    assert 'name="stand_type_id"' in html
    assert 'name="stand_color_id"' in html


def test_coffee_profile_unknown_tab_falls_back_to_monitoring() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps, kind=MachineKind.COFFEE)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get(f"/admin/machines/{machine_id.value}?tab=unknown").text
    assert 'aria-selected="true"' in html
    assert 'data-tab="monitoring"' in html
    assert 'class="admin-workspace-panel" data-tab="equipment" hidden' in html


def test_snack_profile_has_no_equipment_tab_chrome() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get(f"/admin/machines/{machine_id.value}").text
    assert "admin-workspace-tabs" not in html
    assert "Оборудование" not in html
    assert 'name="coffee_machine_model_id"' not in html
    assert 'name="include_in_no_sales_monitoring"' in html
    assert 'name="include_in_visit_photo_review"' in html


def test_machine_profile_post_preserves_tab_in_redirect() -> None:
    app, deps = _build_app(with_master_stores=True)
    machine_id = _seed_machine(deps, kind=MachineKind.COFFEE)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        f"/admin/machines/{machine_id.value}?tab=equipment",
        data={"include_in_no_sales_monitoring": "on"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/admin/machines/{machine_id.value}?tab=equipment"
