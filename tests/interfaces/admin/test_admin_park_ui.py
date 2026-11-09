from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
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
    MoveMachineToStorage,
    MoveMachineToStorageInput,
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

_ADMIN_CSS = (
    Path(__file__).resolve().parents[3] / "src" / "interfaces" / "admin" / "static" / "admin.css"
)

_DEMO = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "interfaces"
    / "admin"
    / "static"
    / "demo-park.html"
)

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


def test_admin_css_sticky_offset_under_app_header() -> None:
    css = _ADMIN_CSS.read_text(encoding="utf-8")
    assert "--admin-app-header-height:" in css
    assert ".admin-app-header" in css
    assert "position: sticky" in css
    assert "top: var(--admin-app-header-height)" in css
    assert "calc(var(--admin-app-header-height)" in css


def test_admin_css_entity_link_visited_reset() -> None:
    css = _ADMIN_CSS.read_text(encoding="utf-8")
    assert "a.admin-entity-link:link" in css
    assert "a.admin-entity-link:visited" in css
    assert "var(--admin-accent)" in css


def test_admin_css_visited_links_keep_their_color() -> None:
    css = _ADMIN_CSS.read_text(encoding="utf-8")
    assert "a:link" in css
    assert "a:visited" in css
    assert "a.admin-sidebar-link:link" in css
    assert "a.admin-sidebar-link:visited" in css
    assert "a.admin-btn:link" in css
    assert "a.admin-btn:visited" in css
    assert "a.admin-btn-secondary:link" in css
    assert "a.admin-btn-secondary:visited" in css
    assert "var(--admin-accent)" in css
    assert "var(--admin-sidebar-fg)" in css


def test_admin_css_defines_admin_btn() -> None:
    css = _ADMIN_CSS.read_text(encoding="utf-8")
    assert ".admin-btn" in css


def test_machines_has_admin_app_header() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/machines")
    assert response.status_code == 200
    assert 'class="admin-app-header"' in response.text
    assert "Парк аппаратов" in response.text or "Парк" in response.text


def test_nav_links_are_button_styled() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert 'href="/admin/roster"' in html
    assert 'href="/admin/machines"' in html


def test_machines_has_no_local_admin_header() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert 'class="admin-header"' not in html


def test_roster_has_no_local_admin_header() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/roster")
    assert response.status_code == 200
    html = response.text
    assert 'class="admin-app-header"' in html
    assert 'class="admin-header"' not in html
    assert "Roster локаций" in html


def test_login_has_no_logout_or_panel_nav() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    html = client.get("/admin/login").text
    assert 'action="/admin/logout"' not in html
    assert 'href="/admin/roster"' not in html
    assert 'href="/admin/machines"' not in html
    assert "Вход" in html


def _install_coffee(deps: AdminHttpDeps) -> str:
    assert deps.master_stores is not None
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    installed = InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=lambda: now,
    ).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    return installed.machine_id.value


def test_machines_list_has_no_storage_action() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    machine_id = _install_coffee(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert "На склад" not in html
    assert f'action="/admin/machines/{machine_id}/storage"' not in html


def test_machines_list_has_relocation_button() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    machine_id = _install_coffee(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert f'href="/admin/machines/{machine_id}/relocate"' in html
    assert "admin-btn" in html
    assert "Релокация" in html


def test_machines_list_has_place_from_storage_button() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    machine_id = _install_coffee(deps)
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    MoveMachineToStorage(
        stores=deps.master_stores,
        now_factory=lambda: now,
    ).execute(
        MoveMachineToStorageInput(
            machine_id=MachineId(machine_id),
            actor_telegram_user_id=1,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert f'href="/admin/machines/{machine_id}/place"' in html
    assert "Со склада" in html
    assert "admin-btn" in html
    assert "На склад" not in html


def test_machines_list_install_is_button() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert 'href="/admin/machines/install"' in html
    assert "Установка" in html
    assert 'class="admin-btn"' in html


def test_machines_list_has_no_status_column() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    _install_coffee(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert ">Статус<" not in html
    assert "active_on_site" not in html


def test_machines_location_link_has_entity_class() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    _install_coffee(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert 'class="admin-entity-link"' in html


def test_machines_list_has_filter_controls() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert 'id="park-search"' in html
    assert 'id="park-kind-filter"' in html
    assert 'id="park-city-filter"' in html
    assert 'id="park-company-filter"' in html
    assert 'id="park-machines-table"' in html
    assert "/admin/static/park.js?v=" in html


def test_park_list_city_column_and_filter_options() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    assert deps.master_stores is not None
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=lambda: now,
    ).execute(
        InstallMachineAtLocationInput(
            name="Кафе А",
            city="Казань",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=lambda: now,
    ).execute(
        InstallMachineAtLocationInput(
            name="Кафе Б",
            city="Москва",
            street="ул. 2",
            house="2",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert "<th" in html and "Город" in html
    assert 'id="park-city-filter"' in html
    assert "без города" not in html.lower()
    assert 'data-city="Казань"' in html
    assert 'data-city="Москва"' in html


def test_park_list_company_column_and_filter_options() -> None:
    occupancy = InMemoryMachineCompanyOccupancyStore()
    display_names = {7: "Орлов М.О.", 11: "Иванов А.А."}
    app, deps = _build_app(
        enabled=True,
        with_master_stores=True,
        company_occupancy_store=occupancy,
        company_display_names=display_names,
    )
    assert deps.master_stores is not None
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    a = InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=lambda: now,
    ).execute(
        InstallMachineAtLocationInput(
            name="Кафе А",
            city="Казань",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    b = InstallMachineAtLocation(
        stores=deps.master_stores,
        now_factory=lambda: now,
    ).execute(
        InstallMachineAtLocationInput(
            name="Кафе Б",
            city="Москва",
            street="ул. 2",
            house="2",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    occupancy.replace_for_machine(
        a.machine_id,
        (MachineCompanyOccupancy(a.machine_id, 7, now, None),),
    )
    occupancy.replace_for_machine(
        b.machine_id,
        (MachineCompanyOccupancy(b.machine_id, 11, now, None),),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines").text
    assert "<th" in html and "Город" in html
    assert "Компания" in html
    assert 'id="park-company-filter"' in html
    assert 'data-company-name="Орлов М.О."' in html
    assert 'data-company-name="Иванов А.А."' in html


def test_relocate_page_has_storage_post_control() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True)
    machine_id = _install_coffee(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get(f"/admin/machines/{machine_id}/relocate").text
    assert "На склад" in html
    assert f'action="/admin/machines/{machine_id}/storage"' in html
    assert 'method="post"' in html.lower() or 'method="POST"' in html
    assert "Релоцировать" in html
    assert "admin-save-bar" in html


def test_demo_park_html_exists_with_chrome_classes() -> None:
    text = _DEMO.read_text(encoding="utf-8")
    assert "admin-app-header" in text
    assert "admin-app-sidebar" in text
    assert "admin-app-header-nav" not in text
    assert "admin-btn" in text
    assert "admin-entity-link" in text
    assert "park-search" in text
    assert "park-kind-filter" in text
    assert "admin.css" in text
    assert "На склад" not in text
    assert "Статус" not in text


def test_demo_park_static_serves_without_login() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    response = client.get("/admin/static/demo-park.html")
    assert response.status_code == 200
    assert "admin-app-header" in response.text
