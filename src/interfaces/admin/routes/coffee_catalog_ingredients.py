from __future__ import annotations

import contextlib
from decimal import Decimal

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.application.form_inventory_policy import (
    FormInventoryPolicyStore,
    seed_coffee_ingredient_policies,
)
from src.application.product_identity import (
    DomainProductRejected,
    create_domain_product,
    hide_domain_product,
    remove_domain_product_link,
    rename_domain_product,
    set_domain_product_packaging,
    unhide_domain_product,
)
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore
from src.domain.product_catalog import ProductUnit
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    page_context,
    require_any_panel,
    require_panel,
)
from src.interfaces.admin.routes.coffee_catalog_support import (
    COFFEE_INGREDIENTS_HREF,
    actor_has_panel,
    ingredient_editor_view,
    ingredient_row,
    ms_catalog_names,
    parse_create_policy_fields,
    parse_pack_size_field,
    parse_unit_field,
    unit_form_key,
)

__all__ = ["register_coffee_catalog_ingredient_routes"]


@beartype
def register_coffee_catalog_ingredient_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    policy_store: FormInventoryPolicyStore | None,
) -> None:
    @router.get(
        "/coffee-ingredients",
        response_class=HTMLResponse,
        name="admin_coffee_ingredients",
    )
    async def coffee_ingredients(request: Request) -> Response:
        actor = require_any_panel(
            request,
            deps,
            (AdminPanel.COFFEE_RECIPES, AdminPanel.DOMAIN_PRODUCTS),
        )
        if isinstance(actor, Response):
            return actor
        can_create = actor_has_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        can_link = actor_has_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        rows = [
            ingredient_row(product)
            for product in store.list_visible()
            if product.kind == "coffee_ingredient"
        ]
        hidden_rows = []
        for number in store.numbers():
            product = store.get_by_number(number)
            if product is not None and product.kind == "coffee_ingredient" and product.hidden:
                hidden_rows.append(ingredient_row(product))
        return _TEMPLATES.TemplateResponse(
            request,
            "coffee_ingredients.html",
            page_context(
                request,
                deps,
                title="Кофейные ингредиенты",
                rows=rows,
                hidden_rows=tuple(hidden_rows),
                flash=None,
                can_create=can_create,
                can_link=can_link,
                can_hide=can_create,
            ),
        )

    def _editor_response(
        request: Request,
        *,
        editor: dict[str, object],
        error: str | None = None,
    ) -> Response:
        can_create = actor_has_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        return _TEMPLATES.TemplateResponse(
            request,
            "coffee_ingredient_editor.html",
            page_context(
                request,
                deps,
                title="Кофейные ингредиенты",
                editor=editor,
                error=error,
                can_create=can_create,
                can_link=actor_has_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS),
                can_hide=can_create,
            ),
        )

    def _parse_editor_fields(
        fields: dict[str, str],
    ) -> tuple[str, ProductUnit | None, Decimal | None]:
        name = fields.get("name", "")
        unit = parse_unit_field(fields.get("unit", ""))
        pack_size = parse_pack_size_field(fields.get("pack_size", ""))
        return name, unit, pack_size

    def _create_editor_from_fields(
        fields: dict[str, str],
        *,
        unit: ProductUnit | None,
    ) -> dict[str, object]:
        base = ingredient_editor_view(None, catalog_names={}, policy_store=None)
        return base | {
            "name": fields.get("name", "").strip(),
            "unit_key": unit_form_key(unit) or "g",
            "pack_size": fields.get("pack_size", ""),
            "loading_radio_n": fields.get("loading_radio_n", "") or "",
            "revision_min_qty": fields.get("revision_min_qty", "") or "",
            "revision_max_qty": fields.get("revision_max_qty", "") or "",
            "warehouse_min_qty": fields.get("warehouse_min_qty", "") or "",
            "warehouse_max_qty": fields.get("warehouse_max_qty", "") or "",
        }

    @router.get(
        "/coffee-ingredients/new",
        response_class=HTMLResponse,
        name="admin_coffee_ingredients_new",
    )
    async def coffee_ingredients_new_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        return _editor_response(
            request,
            editor=ingredient_editor_view(None, catalog_names={}, policy_store=None),
        )

    @router.post(
        "/coffee-ingredients/new",
        name="admin_coffee_ingredients_create",
    )
    async def coffee_ingredients_create(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)
        fields = await form_fields(request, deps)
        name, unit, pack_size = _parse_editor_fields(fields)
        policies = parse_create_policy_fields(fields)
        if policies is None:
            return _editor_response(
                request,
                editor=_create_editor_from_fields(fields, unit=unit),
                error="Заполните политики трёх профилей (Radio N, Min/Max ревизии и склада)",
            )
        loading_line, revision_line, warehouse_line = policies
        try:
            product = create_domain_product(
                name,
                store=store,
                lookup=lookup,
                kind="coffee_ingredient",
                unit=unit,
                pack_size=pack_size,
            )
        except DomainProductRejected as error:
            return _editor_response(
                request,
                editor=_create_editor_from_fields(fields, unit=unit),
                error=error.message,
            )
        if policy_store is not None:
            seed_coffee_ingredient_policies(
                policy_store,
                domain_number=product.number,
                loading=loading_line,
                revision=revision_line,
                warehouse=warehouse_line,
            )
        return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)

    @router.post("/coffee-ingredients/hide", name="admin_coffee_ingredients_hide")
    async def coffee_ingredients_hide(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)
        fields = await form_fields(request, deps)
        product_id = fields.get("domain_product_id", "").strip()
        with contextlib.suppress(DomainProductRejected):
            hide_domain_product(product_id, store=store, contour="coffee")
        return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)

    @router.post("/coffee-ingredients/unhide", name="admin_coffee_ingredients_unhide")
    async def coffee_ingredients_unhide(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)
        fields = await form_fields(request, deps)
        product_id = fields.get("domain_product_id", "").strip()
        with contextlib.suppress(DomainProductRejected):
            unhide_domain_product(product_id, store=store)
        return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)

    @router.get(
        "/coffee-ingredients/{domain_product_id}",
        response_class=HTMLResponse,
        name="admin_coffee_ingredient_editor",
    )
    async def coffee_ingredient_editor_get(
        request: Request,
        domain_product_id: str,
    ) -> Response:
        actor = require_any_panel(
            request,
            deps,
            (AdminPanel.COFFEE_RECIPES, AdminPanel.DOMAIN_PRODUCTS),
        )
        if isinstance(actor, Response):
            return actor
        product = store.get(domain_product_id)
        if product is None or product.kind != "coffee_ingredient" or product.hidden:
            return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)
        return _editor_response(
            request,
            editor=ingredient_editor_view(
                product,
                catalog_names=ms_catalog_names(deps),
                policy_store=policy_store,
            ),
        )

    @router.post(
        "/coffee-ingredients/{domain_product_id}",
        name="admin_coffee_ingredient_save",
    )
    async def coffee_ingredient_editor_post(
        request: Request,
        domain_product_id: str,
    ) -> Response:
        if not origin_allowed(request):
            return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)
        product = store.get(domain_product_id)
        if product is None or product.kind != "coffee_ingredient":
            return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)
        fields = await form_fields(request, deps)
        action = fields.get("action", "save").strip()
        card_href = f"/admin/coffee-ingredients/{domain_product_id}"

        if action == "hide":
            actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
            if isinstance(actor, Response):
                return actor
            with contextlib.suppress(DomainProductRejected):
                hide_domain_product(domain_product_id, store=store, contour="coffee")
            return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=303)

        if action.startswith("unlink:"):
            actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
            if isinstance(actor, Response):
                return actor
            code = action.removeprefix("unlink:")
            with contextlib.suppress(DomainProductRejected):
                remove_domain_product_link(domain_product_id, code, store=store)
            return RedirectResponse(card_href, status_code=303)

        actor = require_panel(request, deps, AdminPanel.COFFEE_RECIPES)
        if isinstance(actor, Response):
            return actor
        name, unit, pack_size = _parse_editor_fields(fields)
        try:
            rename_domain_product(
                domain_product_id,
                name,
                store=store,
                contour="coffee",
            )
            if unit is not None and pack_size is not None:
                set_domain_product_packaging(
                    domain_product_id,
                    unit=unit,
                    pack_size=pack_size,
                    store=store,
                )
        except DomainProductRejected as error:
            refreshed = store.get(domain_product_id) or product
            return _editor_response(
                request,
                editor=ingredient_editor_view(
                    refreshed,
                    catalog_names=ms_catalog_names(deps),
                    policy_store=policy_store,
                ),
                error=error.message,
            )
        return RedirectResponse(card_href, status_code=303)

    @router.get("/domain-products/coffee-ingredients")
    async def coffee_ingredients_nested_get() -> RedirectResponse:
        return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=301)

    @router.post("/domain-products/coffee-ingredients")
    async def coffee_ingredients_nested_post() -> RedirectResponse:
        return RedirectResponse(COFFEE_INGREDIENTS_HREF, status_code=301)
