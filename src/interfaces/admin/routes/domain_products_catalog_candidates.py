from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import Response

from src.application.product_identity import (
    import_catalog_candidates,
    list_catalog_candidates,
)
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore
from src.application.reference_data import ReferenceDataSourceId
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.domain_products_view import (
    CatalogCandidatesImportResultView,
    build_catalog_candidates_import_result_view,
)
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    origin_allowed,
    page_context,
    read_admin_body,
    require_panel,
)

_LOGGER = logging.getLogger(__name__)

__all__ = ["register_domain_products_catalog_candidates_routes"]


@beartype
def register_domain_products_catalog_candidates_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
) -> None:
    store = deps.domain_product_store
    lookup = deps.catalog_product_lookup
    assert store is not None
    assert lookup is not None

    @router.get("/domain-products/catalog-candidates")
    async def catalog_candidates_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        return await asyncio.to_thread(_candidates_page, request, deps, store=store, lookup=lookup)

    @router.post("/domain-products/catalog-candidates")
    async def catalog_candidates_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.DOMAIN_PRODUCTS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_domain_products_origin_reject")
            return Response(status_code=403)
        body = await read_admin_body(request, deps)
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        action = (parsed.get("action") or [""])[-1]
        if action == "refresh-catalog":
            sync = deps.product_catalog_sync
            if sync is not None:
                await sync()
            return await asyncio.to_thread(
                _candidates_page,
                request,
                deps,
                store=store,
                lookup=lookup,
            )
        codes = tuple(value.strip() for value in parsed.get("code", []) if value.strip())
        if not codes:
            _LOGGER.info("admin_domain_products_catalog_import_reject")
            return await asyncio.to_thread(
                _candidates_page,
                request,
                deps,
                store=store,
                lookup=lookup,
                empty_selection_hint="Выберите позиции для импорта.",
            )
        result = await asyncio.to_thread(
            import_catalog_candidates,
            codes,
            store=store,
            lookup=lookup,
            procurement_sync=deps.procurement_sync,
        )
        _LOGGER.info(
            "admin_domain_products_catalog_import",
            extra={
                "created_count": result.created,
                "unchanged_count": result.unchanged,
                "failures_count": len(result.failures),
            },
        )
        return await asyncio.to_thread(
            _candidates_page,
            request,
            deps,
            store=store,
            lookup=lookup,
            import_result=build_catalog_candidates_import_result_view(result),
        )


def _format_catalog_fetched_at(moment: datetime, timezone: ZoneInfo) -> str:
    local = moment.astimezone(timezone)
    return f"Снимок: {local.strftime('%d.%m.%Y %H:%M')}"


def _candidates_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    import_result: CatalogCandidatesImportResultView | None = None,
    empty_selection_hint: str | None = None,
    status_code: int = 200,
) -> Response:
    candidates = list_catalog_candidates(store=store, lookup=lookup)
    catalog_fetched_at = ""
    catalog_sync_error = ""
    snapshot_store = deps.catalog_snapshot_store
    if snapshot_store is not None:
        snapshot = snapshot_store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
        if snapshot is not None:
            catalog_fetched_at = _format_catalog_fetched_at(
                snapshot.last_fetched_at,
                deps.timezone,
            )
            if snapshot.last_sync_error is not None:
                catalog_sync_error = snapshot.last_sync_error.message
    return _TEMPLATES.TemplateResponse(
        request,
        "domain_products_catalog_candidates.html",
        page_context(
            request,
            deps,
            candidates=candidates,
            import_result=import_result,
            empty_selection_hint=empty_selection_hint,
            catalog_fetched_at=catalog_fetched_at,
            catalog_sync_error=catalog_sync_error,
            catalog_refresh_enabled=deps.product_catalog_sync is not None,
        ),
        status_code=status_code,
    )
