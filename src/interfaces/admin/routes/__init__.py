from __future__ import annotations

from pathlib import Path

from beartype import beartype
from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from src.application.service_visits import RefreshScheduledVisitsForRosterChange
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.auth import register_auth_routes
from src.interfaces.admin.routes.coffee_catalog import register_coffee_catalog_routes
from src.interfaces.admin.routes.companies import register_companies_routes
from src.interfaces.admin.routes.domain_products import register_domain_products_routes
from src.interfaces.admin.routes.machine_incidents import register_machine_incidents_routes
from src.interfaces.admin.routes.master_data import (
    _refresh_provider_master_data,
    register_master_data_routes,
)
from src.interfaces.admin.routes.matrix_catalog import (
    _layout_known_product_codes,
    register_matrix_sku_catalog_routes,
)
from src.interfaces.admin.routes.matrix_pricing import register_matrix_pricing_routes
from src.interfaces.admin.routes.micromarket_loading import (
    register_micromarket_loading_routes,
)
from src.interfaces.admin.routes.micromarket_planogram import (
    register_micromarket_planogram_routes,
)
from src.interfaces.admin.routes.nav_settings import register_nav_settings_routes
from src.interfaces.admin.routes.people import register_people_routes
from src.interfaces.admin.routes.roster import (
    _export_mirror_after_roster,
    register_roster_routes,
)
from src.interfaces.admin.routes.settlement_analysis import register_settlement_analysis_routes
from src.interfaces.admin.routes.snack_planograms import register_snack_planograms_routes
from src.interfaces.admin.routes.technicians import _refresh_provider_technicians
from src.interfaces.admin.routes.users import (
    _COMPANY_ROLE_FORM_KEYS,
    _access_rows_from_users_form,
)
from src.interfaces.admin.routes.visit_board import register_visit_board_routes
from src.interfaces.admin.routes.visit_photo_profiles import (
    register_visit_photo_profiles_routes,
)
from src.interfaces.admin.routes.visit_photo_review import register_visit_photo_review_routes

__all__ = [
    "_COMPANY_ROLE_FORM_KEYS",
    "_access_rows_from_users_form",
    "_export_mirror_after_roster",
    "_layout_known_product_codes",
    "_refresh_provider_master_data",
    "_refresh_provider_technicians",
    "RefreshScheduledVisitsForRosterChange",
    "register_admin_routes",
]


@beartype
def register_admin_routes(app: FastAPI, deps: AdminHttpDeps, *, enabled: bool) -> None:
    if not enabled:
        return
    app.mount(
        "/admin/static",
        StaticFiles(directory=str(Path(__file__).parent.parent / "static")),
        name="admin_static",
    )
    router = APIRouter(prefix="/admin", include_in_schema=False)
    register_auth_routes(router, deps)
    register_roster_routes(router, deps)
    if deps.master_stores is not None:
        register_master_data_routes(router, deps)
        if deps.layout_master_enabled and deps.snack_layout_store is not None:
            register_snack_planograms_routes(router, deps)
        if deps.micromarket_planogram_store is not None:
            register_micromarket_planogram_routes(router, deps)
        if (
            deps.micromarket_planogram_store is not None
            and deps.micromarket_stock_store is not None
        ):
            register_micromarket_loading_routes(router, deps)
    if deps.sku_catalog_master_enabled:
        register_matrix_sku_catalog_routes(router, deps)
    if deps.master_stores is not None and deps.matrix_base_margin_store is not None:
        register_matrix_pricing_routes(router, deps)
    register_people_routes(router, deps)
    if deps.companies_enabled and deps.create_company is not None:
        register_companies_routes(router, deps)
    if deps.domain_product_store is not None and deps.catalog_product_lookup is not None:
        register_coffee_catalog_routes(router, deps)
        register_domain_products_routes(router, deps)
    register_visit_board_routes(router, deps)
    register_machine_incidents_routes(router, deps)
    register_visit_photo_review_routes(router, deps)
    register_visit_photo_profiles_routes(router, deps)
    register_settlement_analysis_routes(router, deps)
    register_nav_settings_routes(router, deps)
    app.include_router(router)
