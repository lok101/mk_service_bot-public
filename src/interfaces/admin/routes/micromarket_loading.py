from __future__ import annotations

from beartype import beartype
from fastapi import APIRouter

from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.micromarket_loading_assembly import (
    register_micromarket_loading_assembly_routes,
)
from src.interfaces.admin.routes.micromarket_loading_assembly_tab import (
    _fm_tab_context,
    _loading_tab_context,
)
from src.interfaces.admin.routes.micromarket_loading_cycle import (
    register_micromarket_loading_cycle_routes,
)
from src.interfaces.admin.routes.micromarket_loading_orders import _loading_orders_tab_context
from src.interfaces.admin.routes.micromarket_loading_support import (
    _actor_may_ops_accept,
    _company_roles_may_ops_accept,
    _decimal_at,
)
from src.interfaces.admin.routes.micromarket_planograms import (
    register_micromarket_planograms_routes,
)

__all__ = [
    "register_micromarket_loading_routes",
    "_loading_tab_context",
    "_loading_orders_tab_context",
    "_fm_tab_context",
    "_actor_may_ops_accept",
    "_company_roles_may_ops_accept",
    "_decimal_at",
]


@beartype
def register_micromarket_loading_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    assert stores is not None
    register_micromarket_planograms_routes(router, deps)
    register_micromarket_loading_cycle_routes(router, deps, stores)
    register_micromarket_loading_assembly_routes(router, deps, stores)
