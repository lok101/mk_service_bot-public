from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.application.coffee_bom import upsert_coffee_recipe
from src.application.product_identity import (
    DomainProductRejected,
    create_domain_product,
    set_legacy_ms_code,
)
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore
from src.domain.coffee_bom.models import CoffeeRecipeComponent
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    page_context,
    require_panel,
)

__all__ = ["register_coffee_catalog_drink_routes"]


@beartype
def register_coffee_catalog_drink_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
) -> None:
    recipes = deps.coffee_recipe_repo

    @router.get("/coffee-drinks", response_class=HTMLResponse, name="admin_coffee_drinks")
    async def coffee_drinks(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        ingredients = [
            {
                "id": product.domain_product_id,
                "label": f"{product.number} · {product.name}",
            }
            for product in store.list_visible()
            if product.kind == "coffee_ingredient"
        ]
        rows = []
        for product in store.list_visible():
            if product.kind != "coffee_drink":
                continue
            recipe = recipes.get(product.domain_product_id) if recipes is not None else None
            components = (
                [
                    {
                        "ingredient_product_id": component.ingredient_product_id,
                        "quantity_per_unit": format(component.quantity_per_unit, "f"),
                    }
                    for component in recipe.components
                ]
                if recipe is not None
                else []
            )
            rows.append(
                {
                    "id": product.domain_product_id,
                    "number": product.number,
                    "name": product.name,
                    "legacy_ms_code": product.legacy_ms_code or "",
                    "components": components,
                },
            )
        error = request.query_params.get("error")
        return _TEMPLATES.TemplateResponse(
            request,
            "coffee_drinks.html",
            page_context(
                request,
                deps,
                title="Напитки и состав",
                rows=rows,
                ingredients=ingredients,
                flash=error,
            ),
        )

    @router.post("/coffee-drinks", name="admin_coffee_drinks_create")
    async def coffee_drinks_create(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return RedirectResponse("/admin/coffee-drinks", status_code=303)
        fields = await form_fields(request, deps)
        name = fields.get("name", "")
        legacy = fields.get("legacy_ms_code", "").strip()
        try:
            product = create_domain_product(
                name,
                store=store,
                lookup=lookup,
                kind="coffee_drink",
            )
            if legacy:
                set_legacy_ms_code(
                    product.domain_product_id,
                    legacy,
                    store=store,
                    lookup=lookup,
                )
        except DomainProductRejected:
            pass
        return RedirectResponse("/admin/coffee-drinks", status_code=303)

    @router.post("/coffee-drinks/recipe", name="admin_coffee_drinks_recipe")
    async def coffee_drinks_recipe(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request) or recipes is None:
            return RedirectResponse("/admin/coffee-drinks", status_code=303)
        form = await request.form()
        drink_id = str(form.get("drink_product_id", "")).strip()
        ingredient_ids = [str(value).strip() for value in form.getlist("ingredient_product_id")]
        quantities = [str(value).strip() for value in form.getlist("quantity_per_unit")]
        components: list[CoffeeRecipeComponent] = []
        try:
            for ingredient_id, qty_raw in zip(ingredient_ids, quantities, strict=False):
                if not ingredient_id:
                    continue
                quantity = Decimal(qty_raw)
                components.append(
                    CoffeeRecipeComponent(
                        ingredient_product_id=ingredient_id,
                        quantity_per_unit=quantity,
                    ),
                )
            upsert_coffee_recipe(
                drink_id,
                tuple(components),
                recipe_repo=recipes,
                products=store,
            )
        except (DomainProductRejected, InvalidOperation, ValueError) as exc:
            message = str(exc) or "invalid_recipe"
            return RedirectResponse(
                f"/admin/coffee-drinks?error={quote(message)}",
                status_code=303,
            )
        if deps.refresh_pending_after_bom is not None:
            deps.refresh_pending_after_bom()
        return RedirectResponse("/admin/coffee-drinks", status_code=303)
