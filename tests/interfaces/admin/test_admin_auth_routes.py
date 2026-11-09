from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import (
    NullMaintenanceOnOperationalDayLookup,
)
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.system_user import BotRole, CompanyRole, SystemUser, SystemUserId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_TECH_TG = 2002
_FROZEN_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
_STATIC_DIR = Path(__file__).resolve().parents[3] / "src" / "interfaces" / "admin" / "static"


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


def test_admin_routes_404_when_disabled() -> None:
    app, _deps = _build_app(enabled=False)
    client = TestClient(app)
    assert client.get("/admin/login").status_code == 404
    assert client.get("/admin/roster").status_code == 404


def test_admin_static_css_served_when_enabled() -> None:
    app, _deps = _build_app(enabled=True)
    client = TestClient(app)
    response = client.get("/admin/static/admin.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("content-type", "")
    assert len(response.text) > 0
    assert "settlement-sku-table" in response.text


def test_admin_static_css_404_when_disabled() -> None:
    app, _deps = _build_app(enabled=False)
    client = TestClient(app)
    assert client.get("/admin/static/admin.css").status_code == 404


def test_admin_static_leaflet_served_when_enabled() -> None:
    app, _deps = _build_app(enabled=True)
    client = TestClient(app)
    js = client.get("/admin/static/leaflet.js")
    css = client.get("/admin/static/leaflet.css")
    assert js.status_code == 200
    assert css.status_code == 200
    assert "L." in js.text or "leaflet" in js.text.lower()
    assert len(css.text) > 0


def test_admin_static_leaflet_404_when_disabled() -> None:
    app, _deps = _build_app(enabled=False)
    client = TestClient(app)
    assert client.get("/admin/static/leaflet.js").status_code == 404


def test_telegram_auth_rejects_bad_hash() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    response = client.post(
        "/admin/auth/telegram",
        data={
            "id": str(_ADMIN_TG),
            "auth_date": str(int(_FROZEN_NOW.timestamp())),
            "hash": "deadbeef",
        },
    )
    assert response.status_code == 403
    assert "session" not in response.cookies


def test_telegram_auth_rejects_stale_auth_date() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    response = client.post(
        "/admin/auth/telegram",
        data=_signed_widget_fields(auth_date="1"),
    )
    assert response.status_code == 403


def test_telegram_auth_rejects_non_admin() -> None:
    app, deps = _build_app()
    deps.provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        _admin_rows(role="техник", tg=_TECH_TG),
    )
    client = TestClient(app)
    response = client.post(
        "/admin/auth/telegram",
        data=_signed_widget_fields(tg=_TECH_TG),
    )
    assert response.status_code == 403


def test_telegram_auth_rejects_inactive_admin() -> None:
    app, deps = _build_app()
    deps.provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        _admin_rows(active="нет"),
    )
    client = TestClient(app)
    response = client.post("/admin/auth/telegram", data=_signed_widget_fields())
    assert response.status_code == 403


def test_telegram_auth_sets_cookie_for_active_admin() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    response = client.post(
        "/admin/auth/telegram",
        data=_signed_widget_fields(),
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert response.cookies.get("admin_session")


def test_login_sets_secure_cookie_when_request_scheme_https() -> None:
    app, _deps = _build_app(enabled=True)
    client = TestClient(app, base_url="https://testserver")
    response = client.post(
        "/admin/auth/telegram",
        data=_signed_widget_fields(),
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    set_cookie = response.headers.get("set-cookie", "")
    assert "Secure" in set_cookie or "secure" in set_cookie.lower()


def test_login_page_uses_onauth_not_auth_url() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    html = client.get("/admin/login").text
    assert 'data-telegram-login="mk_bot"' in html
    assert "data-onauth" in html
    assert "data-auth-url" not in html


def test_logout_clears_cookie() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.post("/admin/logout")
    roster = client.get("/admin/roster", follow_redirects=False)
    assert roster.status_code in {302, 303}
    assert "/admin/login" in roster.headers["location"]


def test_admin_css_roster_weekday_checkbox_fills_cell() -> None:
    """happy: weekday checkbox almost fills the table cell."""
    css = (_STATIC_DIR / "admin.css").read_text(encoding="utf-8")
    assert ".admin-roster-weekday" in css
    assert ".admin-roster-weekday-hit" in css
    hit_idx = css.find(".admin-roster-weekday-hit")
    assert hit_idx != -1
    hit_block = css[hit_idx : hit_idx + 500]
    assert "position: absolute" in hit_block or "position:absolute" in hit_block
    box_idx = css.find('td.admin-roster-weekday input[type="checkbox"]')
    if box_idx == -1:
        box_idx = css.find("td.admin-roster-weekday input[type='checkbox']")
    assert box_idx != -1
    box_block = css[box_idx : box_idx + 400]
    assert "min(" in box_block
    assert "100cqh" in box_block
    assert "100cqw" in box_block


def test_admin_css_defines_sticky_chrome_and_save_bar() -> None:
    """happy: CSS markers sticky chrome pin + thead offset + fixed save bar."""
    app, _deps = _build_app(enabled=True)
    client = TestClient(app)
    css = client.get("/admin/static/admin.css").text
    assert "admin-save-bar" in css
    assert "admin-roster-chrome" in css
    assert "admin-roster-chrome-pin" in css
    assert "position: fixed" in css or "position:fixed" in css
    assert "justify-content: flex-end" in css or "justify-content:flex-end" in css
    assert "position: sticky" in css or "position:sticky" in css
    assert "--admin-roster-chrome-pin-offset" in css
    assert "--admin-save-bar-height" in css
    assert "calc(2rem" in css or "padding-bottom" in css
    wrap_block_start = css.find(".admin-table-wrap")
    assert wrap_block_start != -1
    wrap_slice = css[wrap_block_start : wrap_block_start + 200]
    assert "overflow-x: auto" not in wrap_slice
    assert "overflow-x:auto" not in wrap_slice


def test_login_page_links_admin_static_css() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    html = client.get("/admin/login").text
    assert "/admin/static/admin.css?v=" in html
    assert 'rel="icon" href="/admin/static/favicon.svg?v=' in html
    assert 'data-telegram-login="mk_bot"' in html
    assert "data-onauth" in html


def test_admin_static_favicon_served_when_enabled() -> None:
    app, _deps = _build_app(enabled=True)
    client = TestClient(app)
    response = client.get("/admin/static/favicon.svg")
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    assert 'viewBox="0 0 32 32"' in response.text
    assert "#1b2230" in response.text
    assert "#0b6e4f" in response.text
    assert 'aria-label="CL"' in response.text


def test_admin_static_roster_js_served_when_enabled() -> None:
    app, _deps = _build_app(enabled=True)
    client = TestClient(app)
    response = client.get("/admin/static/roster.js")
    assert response.status_code == 200
    body = response.text
    assert "roster-search" in body
    assert "data-machine-id" in body or "machine-id" in body
    assert "hidden" in body
    assert "roster:rows-updated" in body
    assert "data-technician-id" in body


def test_admin_static_roster_map_js_served_when_enabled() -> None:
    app, _deps = _build_app(enabled=True)
    client = TestClient(app)
    response = client.get("/admin/static/roster-map.js")
    assert response.status_code == 200
    body = response.text
    assert "roster-map" in body
    assert "L.circleMarker" in body or "circleMarker" in body
    assert "roster:rows-updated" in body


def test_admin_static_roster_map_js_tooltip_avoids_raw_html_string() -> None:
    app, _deps = _build_app(enabled=True)
    client = TestClient(app)
    body = client.get("/admin/static/roster-map.js").text
    assert "bindTooltip(name || code)" not in body
    assert "textContent" in body or "createTextNode" in body


def test_forged_cookie_redirects_to_login() -> None:
    app, _deps = _build_app(enabled=True)
    client = TestClient(app)
    client.cookies.set(admin_session_cookie_name(), "1.1.deadbeef")
    response = client.get("/admin/roster", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/admin/login" in response.headers["location"]


def test_expired_cookie_redirects_to_login() -> None:
    app, deps = _build_app(enabled=True)
    old = int(_FROZEN_NOW.timestamp()) - deps.session_ttl_seconds - 10
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=old,
        secret=_SESSION_SECRET,
    )
    client = TestClient(app)
    client.cookies.set(admin_session_cookie_name(), token)
    response = client.get("/admin/roster", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/admin/login" in response.headers["location"]


def test_stub_login_sets_cookie_when_enabled() -> None:
    app, _deps = _build_app(stub=True)
    client = TestClient(app)
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert response.cookies.get("admin_session")


def test_stub_login_404_when_disabled() -> None:
    app, _deps = _build_app(stub=False)
    client = TestClient(app)
    assert (
        client.post("/admin/auth/stub", data={"telegram_user_id": str(_ADMIN_TG)}).status_code
        == 404
    )


def test_login_rejects_empty_panels_when_users_enabled() -> None:
    """error: flag on + пустые panels → 403 без cookie."""
    app, deps = _build_app(stub=True, users_enabled=True)
    snap = SystemUsersSnapshot(
        users_by_telegram_id={
            _ADMIN_TG: SystemUser(
                user_id=SystemUserId("1"),
                name="Ops",
                role=BotRole.NONE,
                is_active=True,
                telegram_user_id=_ADMIN_TG,
                technician_id=None,
                company_roles=frozenset(),
            ),
        },
        users_by_technician_id={},
    )
    deps.provider.apply_system_users_snapshot(snap)
    client = TestClient(app)
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert admin_session_cookie_name() not in response.cookies


def test_login_redirects_to_first_allowed_panel() -> None:
    """happy: users_enabled + только ROSTER → Location /admin/roster (не machines)."""
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
                company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
            ),
        },
        users_by_technician_id={},
    )
    deps.provider.apply_system_users_snapshot(snap)
    client = TestClient(app)
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert response.headers["location"] == "/admin/roster"


def test_login_fail_reason_no_panels(caplog: pytest.LogCaptureFixture) -> None:
    """error: login fail reason no_panels в логе при users_enabled."""
    app, deps = _build_app(stub=True, users_enabled=True)
    snap = SystemUsersSnapshot(
        users_by_telegram_id={
            _ADMIN_TG: SystemUser(
                user_id=SystemUserId("1"),
                name="Ops",
                role=BotRole.NONE,
                is_active=True,
                telegram_user_id=_ADMIN_TG,
                technician_id=None,
                company_roles=frozenset(),
            ),
        },
        users_by_technician_id={},
    )
    deps.provider.apply_system_users_snapshot(snap)
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="src.interfaces.admin.http_common"):
        response = client.post(
            "/admin/auth/stub",
            data={"telegram_user_id": str(_ADMIN_TG)},
            follow_redirects=False,
        )
    assert response.status_code == 403
    fail_records = [r for r in caplog.records if r.getMessage() == "admin_login_fail"]
    assert fail_records
    assert fail_records[0].reason == "no_panels"
