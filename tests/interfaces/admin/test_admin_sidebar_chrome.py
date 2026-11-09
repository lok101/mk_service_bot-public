from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_ADMIN_CSS = (
    Path(__file__).resolve().parents[3] / "src" / "interfaces" / "admin" / "static" / "admin.css"
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
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=enabled)
    return app, deps


def test_sidebar_active_prefix_match_machines() -> None:
    from src.interfaces.admin.system_users_view import panel_path_is_active

    assert panel_path_is_active("/admin/machines/42", "/admin/machines") is True
    assert panel_path_is_active("/admin/roster", "/admin/machines") is False


def test_nav_settings_always_mounted_when_admin() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert "/admin/nav-settings" in html


def test_authenticated_has_sidebar_no_header_panel_nav() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert "admin-app-sidebar" in html
    assert "admin-app-header-nav" not in html
    assert 'action="/admin/logout"' in html


def test_logout_in_sidebar_header_title_only() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    header_start = html.find("admin-app-header")
    header_end = html.find("</header>", header_start)
    header_html = html[header_start:header_end]
    assert "Выйти" not in header_html
    assert "admin-sidebar-logout" in html or 'action="/admin/logout"' in html
    assert "Roster" in html


def test_admin_css_defines_sidebar_width_vars() -> None:
    css = _ADMIN_CSS.read_text(encoding="utf-8")
    assert "--admin-sidebar-width-rail" in css
    assert "--admin-sidebar-width-expanded" in css
    assert ".admin-app-sidebar" in css


def test_sidebar_active_class_on_machines_child() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/machines/install").text
    assert "is-active" in html


def test_login_has_no_sidebar() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True)
    client = TestClient(app)
    html = client.get("/admin/login").text
    assert "admin-app-sidebar" not in html


def test_sidebar_includes_sku_catalog_link_when_flag_on() -> None:
    from tests.interfaces.admin.test_matrix_sku_catalog_routes import (
        _authed_client,
        _build_catalog_app,
    )

    app, _deps, _store = _build_catalog_app(
        sku_catalog_master_enabled=True,
        with_master_panel=True,
    )
    client = _authed_client(app)
    response = client.get("/admin/machines")
    assert response.status_code == 200
    assert "/admin/matrix-sku-catalog" in response.text
    assert "SKU матрицы" in response.text


def test_sidebar_omits_sku_catalog_link_when_flag_off() -> None:
    from tests.interfaces.admin.test_matrix_sku_catalog_routes import (
        _authed_client,
        _build_catalog_app,
    )

    app, _deps, _store = _build_catalog_app(sku_catalog_master_enabled=False)
    client = _authed_client(app)
    response = client.get("/admin/machines")
    assert response.status_code == 200
    assert "/admin/matrix-sku-catalog" not in response.text
