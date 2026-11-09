from __future__ import annotations

from beartype import beartype
from fastapi import APIRouter

from src.application.product_identity import BorderRegistrationStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.coffee_catalog_border import (
    register_coffee_catalog_border_routes,
)
from src.interfaces.admin.routes.coffee_catalog_drinks import (
    register_coffee_catalog_drink_routes,
)
from src.interfaces.admin.routes.coffee_catalog_ingredients import (
    register_coffee_catalog_ingredient_routes,
)
from src.interfaces.admin.routes.coffee_catalog_policies import (
    register_coffee_catalog_policy_routes,
)

__all__ = ["register_coffee_catalog_routes"]


@beartype
def register_coffee_catalog_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    store = deps.domain_product_store
    lookup = deps.catalog_product_lookup
    policy_store = deps.form_inventory_policy_store
    border = deps.border_registration_store
    if store is None or lookup is None:
        return

    register_coffee_catalog_ingredient_routes(
        router,
        deps,
        store=store,
        lookup=lookup,
        policy_store=policy_store,
    )
    register_coffee_catalog_policy_routes(
        router,
        deps,
        store=store,
        policy_store=policy_store,
    )
    register_coffee_catalog_drink_routes(
        router,
        deps,
        store=store,
        lookup=lookup,
    )
    if isinstance(border, BorderRegistrationStore):
        register_coffee_catalog_border_routes(
            router,
            deps,
            store=store,
            lookup=lookup,
            border=border,
        )
