from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.interfaces.admin.admin_route_baseline import ADMIN_ROUTE_BASELINE
from tests.interfaces.admin.test_admin_auth_routes import _build_app
from tests.interfaces.admin.test_system_users_routes import _build_users_app

from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.route_catalog import collect_admin_routes

AUTH_ROUTE_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/admin/login"),
        ("POST", "/admin/auth/telegram"),
        ("POST", "/admin/logout"),
        ("POST", "/admin/auth/stub"),
    }
)

ROSTER_ROUTE_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/admin/roster"),
        ("POST", "/admin/roster"),
        ("POST", "/admin/roster/draft"),
        ("POST", "/admin/roster/apply"),
        ("POST", "/admin/roster/reset"),
    }
)

MASTER_DATA_ROUTE_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/admin/domain-products"),
        ("GET", "/admin/domain-products/new"),
        ("GET", "/admin/domain-products/{domain_product_id}"),
        ("POST", "/admin/domain-products/new"),
        ("POST", "/admin/domain-products/import"),
        ("POST", "/admin/domain-products/{domain_product_id}"),
        ("GET", "/admin/machines"),
        ("GET", "/admin/machines/install"),
        ("POST", "/admin/machines/install"),
        ("GET", "/admin/machines/{machine_id}"),
        ("GET", "/admin/machines/{machine_id}/layout"),
        ("POST", "/admin/machines/{machine_id}"),
        ("POST", "/admin/machines/{machine_id}/layout"),
        ("POST", "/admin/machines/{machine_id}/layout/copy"),
        ("POST", "/admin/machines/{machine_id}/layout/apply"),
        ("GET", "/admin/machines/{machine_id}/relocate"),
        ("POST", "/admin/machines/{machine_id}/relocate"),
        ("GET", "/admin/machines/{machine_id}/place"),
        ("POST", "/admin/machines/{machine_id}/place"),
        ("POST", "/admin/machines/{machine_id}/storage"),
        ("GET", "/admin/locations/{location_id}"),
        ("POST", "/admin/locations/{location_id}"),
    }
)

MATRIX_ROUTE_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/admin/matrix-sku-catalog"),
        ("POST", "/admin/matrix-sku-catalog"),
        ("GET", "/admin/matrix-pricing"),
        ("POST", "/admin/matrix-pricing"),
    }
)

PEOPLE_ROUTE_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/admin/users"),
        ("POST", "/admin/users"),
        ("GET", "/admin/technicians"),
        ("POST", "/admin/technicians"),
        ("GET", "/admin/technicians/{technician_id}"),
        ("POST", "/admin/technicians/{technician_id}"),
    }
)

VISIT_SETTLEMENT_NAV_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/admin/visit-board"),
        ("GET", "/admin/machine-incidents"),
        ("GET", "/admin/machine-incidents/history"),
        ("POST", "/admin/machine-incidents/{machine_id}/mute"),
        ("POST", "/admin/machine-incidents/{machine_id}/mute-cancel"),
        ("POST", "/admin/machine-incidents/{machine_id}/engineer-wait"),
        ("GET", "/admin/settlement-analysis"),
        ("POST", "/admin/settlement-analysis/prefs"),
        ("GET", "/admin/settlement-analysis/sessions/{session_id}"),
        ("GET", "/admin/settlement-analysis/periods/{period_id}"),
        ("GET", "/admin/nav-settings"),
        ("POST", "/admin/nav-settings"),
    }
)


def _build_minimal_admin_app() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_app(enabled=True)


def _build_admin_app_stub_enabled() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_app(enabled=True, stub=True)


def _build_full_feature_admin_app() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        with_master_stores=True,
        with_visit_board=True,
        technicians_enabled=True,
        settlement_analysis_enabled=True,
        sku_catalog_master_enabled=True,
    )


def _build_roster_admin_app() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_minimal_admin_app()


def _build_master_data_admin_app() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_full_feature_admin_app()


def _build_matrix_admin_app() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_full_feature_admin_app()


def _build_people_admin_app() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_full_feature_admin_app()


def test_require_panel_redirects_without_cookie() -> None:
    app, _deps = _build_minimal_admin_app()
    client = TestClient(app)
    response = client.get("/admin/roster", follow_redirects=False)
    assert response.status_code in {302, 303, 307}
    assert "/admin/login" in response.headers.get("location", "")


def test_http_common_exports_require_panel_and_origin_allowed() -> None:
    from src.interfaces.admin import http_common

    assert callable(http_common.require_panel)
    assert callable(http_common.origin_allowed)


def test_auth_router_characterization_paths_unchanged() -> None:
    app, _deps = _build_admin_app_stub_enabled()
    routes = collect_admin_routes(app)
    assert routes >= AUTH_ROUTE_BASELINE


def test_roster_router_characterization_paths_unchanged() -> None:
    app, _deps = _build_roster_admin_app()
    routes = collect_admin_routes(app)
    assert routes >= ROSTER_ROUTE_BASELINE


def test_master_data_router_characterization_paths_unchanged() -> None:
    app, _deps = _build_master_data_admin_app()
    routes = collect_admin_routes(app)
    assert routes >= MASTER_DATA_ROUTE_BASELINE
    assert routes == ADMIN_ROUTE_BASELINE


def test_matrix_router_characterization_paths_unchanged() -> None:
    app, _deps = _build_matrix_admin_app()
    routes = collect_admin_routes(app)
    assert routes >= MATRIX_ROUTE_BASELINE
    assert routes == ADMIN_ROUTE_BASELINE


def test_people_router_characterization_paths_unchanged() -> None:
    app, _deps = _build_people_admin_app()
    routes = collect_admin_routes(app)
    assert routes >= PEOPLE_ROUTE_BASELINE
    assert routes == ADMIN_ROUTE_BASELINE


def test_visit_settlement_nav_characterization_paths_unchanged() -> None:
    app, _deps = _build_full_feature_admin_app()
    routes = collect_admin_routes(app)
    assert routes >= VISIT_SETTLEMENT_NAV_BASELINE
    assert routes == ADMIN_ROUTE_BASELINE


def test_admin_route_baseline_unchanged() -> None:
    app, _deps = _build_full_feature_admin_app()
    assert collect_admin_routes(app) == ADMIN_ROUTE_BASELINE
