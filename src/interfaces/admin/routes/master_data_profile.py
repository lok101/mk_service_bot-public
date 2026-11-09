from __future__ import annotations

from fastapi import APIRouter

from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.master_data_profile_layout import (
    register_master_data_profile_layout_routes,
)
from src.interfaces.admin.routes.master_data_profile_settings import (
    register_master_data_profile_settings_routes,
)
from src.interfaces.admin.routes.master_data_profile_workspace import (
    render_machine_planogram_workspace,
)

__all__ = [
    "register_master_data_profile_routes",
    "render_machine_planogram_workspace",
]


def register_master_data_profile_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    register_master_data_profile_settings_routes(router, deps)
    register_master_data_profile_layout_routes(router, deps)
