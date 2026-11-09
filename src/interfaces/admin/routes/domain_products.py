from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from src.application.product_identity import (
    DomainProduct,
    DomainProductRejected,
    catalog_card_window,
    create_domain_product,
    hide_domain_product,
    link_domain_product,
    rename_domain_product,
)
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore
from src.application.reference_data import ReferenceDataSourceId
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.domain_products_view import (
    DomainProductEditorView,
    DomainProductImportResultView,
    build_domain_products_list_view,
    editor_from_product,
    empty_domain_product_editor,
)
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    page_context,
    read_admin_body,
    require_panel,
)

_LOGGER = logging.getLogger(__name__)

__all__ = ["register_domain_products_routes"]


def _format_catalog_fetched_at(moment: datetime, timezone: ZoneInfo) -> str:
    local = moment.astimezone(timezone)
    return f"Снимок: {local.strftime('%d.%m.%Y %H:%M')}"


@beartype
def _coffee_panel_redirect(product: DomainProduct) -> RedirectResponse | None:
    if product.kind == "coffee_ingredient":
        return RedirectResponse("/admin/coffee-ingredients", status_code=303)
    if product.kind == "coffee_drink":
        return RedirectResponse("/admin/coffee-drinks", status_code=303)
    return None


@beartype
def register_domain_products_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    store = deps.domain_product_store
    lookup = deps.catalog_product_lookup
    assert store is not None
    assert lookup is not None

    @router.get("/domain-products")
    async def domain_products_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        return await asyncio.to_thread(_list_page, request, deps, store=store, lookup=lookup)

    @router.get("/domain-products/new")
    async def domain_products_new_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        return _editor_page(request, deps, editor=empty_domain_product_editor())

    @router.post("/domain-products/new")
    async def domain_products_new_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_domain_products_origin_reject")
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        name = fields.get("name", "")
        try:
            product = await asyncio.to_thread(
                _create_from_post,
                name,
                store=store,
                lookup=lookup,
            )
        except DomainProductRejected as exc:
            _LOGGER.info("admin_domain_products_reject", extra={"reason": exc.message})
            return _editor_page(
                request,
                deps,
                editor=replace(empty_domain_product_editor(), name=name),
                error=exc.message,
                status_code=400,
            )
        return RedirectResponse(
            f"/admin/domain-products/{product.domain_product_id}",
            status_code=303,
        )

    @router.post("/domain-products/quick")
    async def domain_products_quick_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_domain_products_origin_reject")
            return Response(status_code=403)
        raw = await read_admin_body(request, deps)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        name = body.get("name", "") if isinstance(body, dict) else ""
        try:
            product = await asyncio.to_thread(
                _create_from_post,
                name if isinstance(name, str) else "",
                store=store,
                lookup=lookup,
            )
        except DomainProductRejected as exc:
            return JSONResponse({"error": exc.message}, status_code=400)
        _LOGGER.info(
            "admin_domain_product_quick_create",
            extra={"domain_product_id": product.domain_product_id},
        )
        return JSONResponse(
            {
                "domain_product_id": product.domain_product_id,
                "name": product.name,
                "number": product.number,
                "catalog_code": product.catalog_code,
            },
        )

    @router.get("/domain-products/catalog-cards")
    async def domain_products_catalog_cards(request: Request, q: str = "") -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor

        def _catalog_cards_payload() -> dict[str, object]:
            window = catalog_card_window(q, cards=lookup.products())
            return {
                "cards": [
                    {
                        "code": hit.code,
                        "name": hit.name,
                        "archived": hit.archived,
                        "taken": store.get_by_catalog_code(hit.code) is not None,
                    }
                    for hit in window.hits
                ],
                "truncated": window.truncated,
            }

        payload = await asyncio.to_thread(_catalog_cards_payload)
        return JSONResponse(payload)

    from src.interfaces.admin.routes.domain_products_catalog_candidates import (
        register_domain_products_catalog_candidates_routes,
    )
    from src.interfaces.admin.routes.domain_products_import import (
        register_domain_products_import_routes,
    )

    register_domain_products_import_routes(router, deps)
    register_domain_products_catalog_candidates_routes(router, deps)

    @router.get("/domain-products/{domain_product_id}")
    async def domain_products_card_get(
        request: Request,
        domain_product_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        product = await asyncio.to_thread(store.get, domain_product_id)
        if product is None:
            return Response(status_code=404)
        coffee_redirect = _coffee_panel_redirect(product)
        if coffee_redirect is not None:
            return coffee_redirect
        return _editor_page(
            request,
            deps,
            editor=_editor_from_product(product, deps=deps, lookup=lookup),
        )

    @router.post("/domain-products/{domain_product_id}")
    async def domain_products_card_post(
        request: Request,
        domain_product_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        product = await asyncio.to_thread(store.get, domain_product_id)
        if product is None:
            return Response(status_code=404)
        coffee_redirect = _coffee_panel_redirect(product)
        if coffee_redirect is not None:
            return coffee_redirect
        if not origin_allowed(request):
            _LOGGER.info("admin_domain_products_origin_reject")
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        if fields.get("action") == "hide":
            try:
                await asyncio.to_thread(hide_domain_product, domain_product_id, store=store)
            except DomainProductRejected as exc:
                _LOGGER.info("admin_domain_products_reject", extra={"reason": exc.message})
                return Response(status_code=400)
            return RedirectResponse("/admin/domain-products", status_code=303)
        name = fields.get("name", "")
        catalog_code = fields.get("catalog_code", "")
        if fields.get("action") == "refresh-catalog":
            sync = deps.product_catalog_sync
            if sync is not None:
                await sync()
            current = store.get(domain_product_id)
            assert current is not None
            drafted = replace(
                _editor_from_product(current, deps=deps, lookup=lookup),
                name=name,
                catalog_code=catalog_code,
            )
            return _editor_page(request, deps, editor=drafted)
        try:
            await asyncio.to_thread(
                rename_domain_product,
                domain_product_id,
                name,
                store=store,
            )
        except DomainProductRejected as exc:
            _LOGGER.info("admin_domain_products_reject", extra={"reason": exc.message})
            current = store.get(domain_product_id)
            assert current is not None
            return _editor_page(
                request,
                deps,
                editor=replace(
                    _editor_from_product(current, deps=deps, lookup=lookup),
                    name=name,
                ),
                error=exc.message,
                status_code=400,
            )
        current = store.get(domain_product_id)
        assert current is not None
        code = catalog_code.strip()
        if code and code != (current.catalog_code or ""):
            try:
                await asyncio.to_thread(
                    link_domain_product,
                    domain_product_id,
                    code,
                    store=store,
                    lookup=lookup,
                    procurement_sync=deps.procurement_sync,
                )
            except DomainProductRejected as exc:
                _LOGGER.info(
                    "admin_domain_products_reject",
                    extra={"reason": exc.message},
                )
                after = store.get(domain_product_id)
                assert after is not None
                return _editor_page(
                    request,
                    deps,
                    editor=replace(
                        _editor_from_product(after, deps=deps, lookup=lookup),
                        catalog_code=catalog_code,
                    ),
                    error=exc.message,
                    status_code=400,
                )
        return RedirectResponse(
            f"/admin/domain-products/{domain_product_id}",
            status_code=303,
        )


def _create_from_post(
    name: str,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
) -> DomainProduct:
    return create_domain_product(name, store=store, lookup=lookup)


def _editor_from_product(
    product: DomainProduct,
    *,
    deps: AdminHttpDeps,
    lookup: CatalogProductLookup,
) -> DomainProductEditorView:
    return editor_from_product(
        product,
        lookup=lookup,
        mirror_enabled=deps.procurement_mirror_enabled,
        mirrors=deps.procurement_mirror_store,
        timezone=deps.timezone,
    )


def _list_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    import_result: DomainProductImportResultView | None = None,
    status_code: int = 200,
) -> Response:
    view = build_domain_products_list_view(
        store=store,
        lookup=lookup,
        mirror_enabled=deps.procurement_mirror_enabled,
        mirrors=deps.procurement_mirror_store,
    )
    return _TEMPLATES.TemplateResponse(
        request,
        "domain_products.html",
        page_context(
            request,
            deps,
            rows=view.rows,
            import_result=import_result,
            procurement_mirror_enabled=view.procurement_mirror_enabled,
            domain_products_tab="products",
        ),
        status_code=status_code,
    )


def _with_catalog_meta(
    editor: DomainProductEditorView,
    *,
    deps: AdminHttpDeps,
) -> DomainProductEditorView:
    if editor.is_new:
        return editor
    fetched = ""
    error = ""
    store = deps.catalog_snapshot_store
    if store is not None:
        snapshot = store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
        if snapshot is not None:
            fetched = _format_catalog_fetched_at(snapshot.last_fetched_at, deps.timezone)
            if snapshot.last_sync_error is not None:
                error = snapshot.last_sync_error.message
    return replace(
        editor,
        catalog_fetched_at=fetched,
        catalog_sync_error=error,
        catalog_refresh_enabled=deps.product_catalog_sync is not None,
    )


def _editor_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    editor: DomainProductEditorView,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    editor = _with_catalog_meta(editor, deps=deps)
    return _TEMPLATES.TemplateResponse(
        request,
        "domain_product_editor.html",
        page_context(request, deps, editor=editor, error=error),
        status_code=status_code,
    )
