from __future__ import annotations

from beartype import beartype
from fastapi import APIRouter

from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.coffee_equipment import register_coffee_equipment_routes
from src.interfaces.admin.routes.master_data_park import (
    _refresh_provider_master_data,
    register_master_data_park_routes,
)
from src.interfaces.admin.routes.master_data_profile import register_master_data_profile_routes
from src.interfaces.admin.routes.matrix_catalog import (
    _layout_known_product_codes,
    _load_snack_ms_by_code,
)

__all__ = [
    "_layout_known_product_codes",
    "_load_snack_ms_by_code",
    "_refresh_provider_master_data",
    "register_master_data_routes",
]


@beartype
def register_master_data_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    register_master_data_park_routes(router, deps)
    register_master_data_profile_routes(router, deps)
    register_coffee_equipment_routes(router, deps)
