from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.interfaces.admin.test_machine_layout_profile import (
    _ADMIN_TG,
    _SESSION_SECRET,
    _TECH_TG,
    _authed_client,
    _build_app,
    _seed_machine,
)
from tests.interfaces.admin.test_machine_layout_profile import (
    _FROZEN_NOW as _PROFILE_FROZEN_NOW,
)
from tests.interfaces.admin.test_matrix_sku_catalog_routes import (
    _FROZEN_NOW as _CATALOG_FROZEN_NOW,
)
from tests.interfaces.admin.test_matrix_sku_catalog_routes import (
    _build_catalog_app,
    _signed_widget_fields,
)
from tests.interfaces.admin.test_settlement_analysis_routes import (
    _build_app as _build_settlement_app,
)
from tests.interfaces.admin.test_settlement_analysis_routes import (
    _login,
)

from src.application.master_data import MachineKind
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_EVIL = {"Origin": "https://evil.example", "Content-Type": "application/x-www-form-urlencoded"}

_SAME_ORIGIN = {
    "Origin": "http://testserver",
    "Content-Type": "application/x-www-form-urlencoded",
}


def _session_client(app: FastAPI, *, issued_at: int) -> TestClient:
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=issued_at,
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    return client


def test_machine_profile_post_rejects_foreign_origin() -> None:
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{snack_id.value}",
        content="include_in_no_sales_monitoring=on",
        headers=_EVIL,
    )
    assert response.status_code == 403


def test_machine_profile_post_rejects_foreign_referer_without_origin() -> None:
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{snack_id.value}",
        content="include_in_no_sales_monitoring=on",
        headers={
            "Referer": "https://evil.example/x",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert response.status_code == 403


def test_matrix_sku_catalog_post_rejects_foreign_origin() -> None:
    app, _deps, _store = _build_catalog_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/matrix-sku-catalog",
        content="action=bulk_save&product_code=1616&display_name=x&capacity=0&product_multiplier=1",
        headers=_EVIL,
    )
    assert response.status_code == 403


def test_settlement_analysis_prefs_post_rejects_foreign_origin() -> None:
    app, _deps, _prefs = _build_settlement_app()
    client = TestClient(app)
    _login(client)
    response = client.post(
        "/admin/settlement-analysis/prefs",
        data={"allowed_loss_pct": "1"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_machine_layout_copy_post_rejects_foreign_origin() -> None:
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app)
    response = client.post(
        f"/admin/machines/{snack_id.value}/layout/copy",
        data={"source_machine_id": "OTHER"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "kind",
    ["profile", "sku_catalog", "settlement_prefs"],
)
def test_admin_post_oversized_body_returns_413_for_scope_routes(kind: str) -> None:
    oversized = "x" * 64
    headers = {
        "Origin": "http://testserver",
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(oversized)),
    }
    if kind == "profile":
        app, deps, _layouts, _stock = _build_app(admin_max_body_bytes=32)
        snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
        client = _session_client(app, issued_at=int(_PROFILE_FROZEN_NOW.timestamp()))
        response = client.post(
            f"/admin/machines/{snack_id.value}",
            content=oversized,
            headers=headers,
        )
    elif kind == "sku_catalog":
        app, _deps, _store = _build_catalog_app(admin_max_body_bytes=32)
        client = _session_client(app, issued_at=int(_CATALOG_FROZEN_NOW.timestamp()))
        response = client.post(
            "/admin/matrix-sku-catalog",
            content=oversized,
            headers=headers,
        )
    else:
        app, _deps, _prefs = _build_settlement_app(admin_max_body_bytes=32)
        client = TestClient(app)
        _login(client)
        response = client.post(
            "/admin/settlement-analysis/prefs",
            content=oversized,
            headers=headers,
        )
    assert response.status_code == 413


def test_matrix_sku_catalog_post_unknown_action_returns_400() -> None:
    app, _deps, _store = _build_catalog_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/matrix-sku-catalog",
        content="action=noop",
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 400
    assert "unknown action" in response.text


def test_matrix_sku_catalog_post_mismatched_lists_returns_400() -> None:
    app, _deps, _store = _build_catalog_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/matrix-sku-catalog",
        content="action=bulk_save&product_code=1616&display_name=a&capacity=0",
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 400
    assert "mismatched form lists" in response.text


def test_matrix_sku_catalog_forbidden_without_panel() -> None:
    app, _deps, _store = _build_catalog_app(with_master_panel=False)
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_TECH_TG,
        issued_at=int(_CATALOG_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    response = client.get("/admin/matrix-sku-catalog")
    assert response.status_code == 403


def test_matrix_sku_catalog_post_forbidden_without_panel() -> None:
    app, _deps, _store = _build_catalog_app(with_master_panel=False)
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_TECH_TG,
        issued_at=int(_CATALOG_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    response = client.post(
        "/admin/matrix-sku-catalog",
        content="action=bulk_save&product_code=1616&display_name=x&capacity=0&product_multiplier=1",
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 403


def test_machine_profile_post_requires_master_data_panel() -> None:
    app, deps, _layouts, _stock = _build_app(with_master_panel=False)
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = _authed_client(app, tg=_TECH_TG)
    response = client.post(
        f"/admin/machines/{snack_id.value}",
        content="include_in_no_sales_monitoring=on",
        headers=_SAME_ORIGIN,
    )
    assert response.status_code == 403


def test_machine_profile_get_requires_login() -> None:
    app, deps, _layouts, _stock = _build_app()
    snack_id = _seed_machine(deps, kind=MachineKind.SNACK)
    client = TestClient(app)
    response = client.get(f"/admin/machines/{snack_id.value}", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/admin/login" in (response.headers.get("location") or "")


def test_logout_post_without_origin_succeeds() -> None:
    app, _deps, _layouts, _stock = _build_app()
    client = _authed_client(app)
    assert client.cookies.get(admin_session_cookie_name())
    response = client.post("/admin/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin/login")
    assert admin_session_cookie_name() not in response.cookies
