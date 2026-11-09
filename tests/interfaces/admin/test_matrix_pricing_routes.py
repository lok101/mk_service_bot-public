from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.application.matrix_automation.fixtures.curved_margin_params import curved_margin_params

from src.application.master_data import InMemoryMasterDataStores
from src.application.matrix_automation.base_margin_store_memory import InMemoryMatrixBaseMarginStore
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.matrix_pricing import calculate_sell_price
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_TECH_TG = 2002
_FROZEN_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
_ORIGIN = {"Origin": "http://testserver"}


def _widget_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _signed_widget_fields(*, tg: int = _ADMIN_TG) -> dict[str, str]:
    fields = {
        "id": str(tg),
        "auth_date": str(int(_FROZEN_NOW.timestamp())),
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


def _valid_scale_form() -> dict[str, str]:
    return {
        "scale_price_min": "10",
        "scale_price_max": "500",
        "scale_rate_max": "20",
        "scale_rate_min": "20",
        "curvature": "1",
        "margin_floor": "20",
        "rounding_last_digits": "0,5",
    }


def _build_pricing_app(
    *,
    with_matrix_pricing_panel: bool = True,
) -> tuple[FastAPI, AdminHttpDeps, InMemoryMatrixBaseMarginStore]:
    provider = ReferenceDataProvider()
    role = "администратор" if with_matrix_pricing_panel else "техник"
    tg = _ADMIN_TG if with_matrix_pricing_panel else _TECH_TG
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            *_admin_rows(role=role, tg=tg),
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
    provider.configure_roster(enabled=True, store=roster_store)
    master_stores = InMemoryMasterDataStores()
    store = InMemoryMatrixBaseMarginStore()
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
        matrix_base_margin_store=store,
        scale_price_min_bound=Decimal("10"),
        scale_price_max_bound=Decimal("500"),
        scale_rate_min_bound=Decimal("0.1"),
        scale_rate_max_bound=Decimal("2.0"),
        curvature_min=Decimal("0.5"),
        curvature_max=Decimal("3"),
        margin_floor_min=Decimal("10"),
        margin_floor_max=Decimal("100"),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps, store


def _authed_client(app: FastAPI, *, tg: int = _ADMIN_TG) -> TestClient:
    client = TestClient(app)
    if tg == _ADMIN_TG:
        client.post("/admin/auth/telegram", data=_signed_widget_fields())
    else:
        token = pack_admin_session(
            telegram_user_id=tg,
            issued_at=int(_FROZEN_NOW.timestamp()),
            secret=_SESSION_SECRET,
        )
        client.cookies.set(admin_session_cookie_name(), token)
    return client


def test_matrix_pricing_get_ok() -> None:
    app, _deps, store = _build_pricing_app()
    store.save(curved_margin_params())
    r = _authed_client(app).get("/admin/matrix-pricing")
    assert r.status_code == 200
    assert 'name="scale_price_min"' in r.text
    assert "Минимум шкалы" in r.text
    assert ">20<" in r.text or 'value="20"' in r.text


def test_matrix_pricing_post_accepts_percent_rates() -> None:
    app, _deps, store = _build_pricing_app()
    data = _valid_scale_form()
    data["scale_rate_max"] = "65"
    data["scale_rate_min"] = "40"
    r = _authed_client(app).post(
        "/admin/matrix-pricing",
        data=data,
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = store.get()
    assert saved is not None
    assert saved.scale_rate_max == Decimal("0.65")
    assert saved.scale_rate_min == Decimal("0.4")


def test_matrix_pricing_post_rejects_unordered_shows_ru_error() -> None:
    app, _deps, store = _build_pricing_app()
    data = _valid_scale_form()
    data["scale_rate_max"] = "40"
    data["scale_rate_min"] = "65"
    r = _authed_client(app).post(
        "/admin/matrix-pricing",
        data=data,
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "Наценка вне допустимого диапазона" in r.text
    assert store.get() is None


def test_matrix_pricing_get_empty_store_shows_form() -> None:
    app, _deps, store = _build_pricing_app()
    assert store.get() is None
    r = _authed_client(app).get("/admin/matrix-pricing")
    assert r.status_code == 200
    assert 'name="scale_price_min"' in r.text


def test_matrix_pricing_403_without_panel() -> None:
    app, _deps, _store = _build_pricing_app(with_matrix_pricing_panel=False)
    assert _authed_client(app, tg=_TECH_TG).get("/admin/matrix-pricing").status_code == 403


def test_matrix_pricing_post_saves() -> None:
    app, _deps, store = _build_pricing_app()
    r = _authed_client(app).post(
        "/admin/matrix-pricing",
        data=_valid_scale_form(),
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert store.get() is not None


def test_matrix_pricing_post_rejects_empty() -> None:
    app, _deps, store = _build_pricing_app()
    r = _authed_client(app).post(
        "/admin/matrix-pricing",
        data={},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert store.get() is None


def test_matrix_pricing_post_rejects_unordered() -> None:
    app, _deps, store = _build_pricing_app()
    data = _valid_scale_form()
    data["scale_price_min"] = "100"
    data["scale_price_max"] = "10"
    r = _authed_client(app).post(
        "/admin/matrix-pricing",
        data=data,
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert store.get() is None


def test_matrix_pricing_has_save_bar() -> None:
    app, _deps, _store = _build_pricing_app()
    html = _authed_client(app).get("/admin/matrix-pricing").text
    assert html.count('class="admin-save-bar"') == 1


def test_matrix_pricing_preview_sell() -> None:
    params = curved_margin_params()
    expected = str(
        calculate_sell_price(
            purchase=Decimal("100"),
            product_multiplier=Decimal("1"),
            matrix_multiplier=Decimal("1"),
            params=params,
        )
    )
    app, _deps, store = _build_pricing_app()
    store.save(params)
    client = _authed_client(app)
    response = client.get("/admin/matrix-pricing", params={"preview_purchase": "100"})
    assert response.status_code == 200
    assert expected in response.text


def test_sidebar_includes_matrix_pricing_when_allowed() -> None:
    app, _deps, _store = _build_pricing_app()
    html = _authed_client(app).get("/admin/matrix-pricing").text
    assert 'href="/admin/matrix-pricing"' in html
    assert "Правила цены" in html
