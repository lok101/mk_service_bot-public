from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.matrix_automation import (
    BulkSaveMatrixSku,
    BulkSaveMatrixSkuInput,
    BulkSaveMatrixSkuRow,
    MatrixSkuCommandRejected,
    MatrixSkuListRow,
    build_matrix_sku_catalog_rows,
)
from src.application.shared import parse_sheet_decimal
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
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
_MATRIX_SKU_CATALOG_PATH = "/admin/matrix-sku-catalog"

__all__ = [
    "_layout_known_product_codes",
    "_load_snack_ms_by_code",
    "register_matrix_sku_catalog_routes",
]


@beartype
def register_matrix_sku_catalog_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    @router.get("/matrix-sku-catalog")
    async def matrix_sku_catalog_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MATRIX_SKU_CATALOG)
        if isinstance(actor, Response):
            return actor
        try:
            ms = await _load_snack_ms_by_code(deps)
        except Exception:
            _LOGGER.exception("admin_matrix_sku_catalog_ms_fail")
            return await _matrix_sku_catalog_page(
                request,
                deps,
                rows=(),
                error="Не удалось загрузить ассортимент МойСклад",
                status_code=502,
            )
        store = deps.matrix_sku_catalog_store
        if store is None:
            return Response(status_code=404)
        rows = build_matrix_sku_catalog_rows(ms, store.list_all())
        return await _matrix_sku_catalog_page(request, deps, rows=rows)

    @router.post("/matrix-sku-catalog")
    async def matrix_sku_catalog_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MATRIX_SKU_CATALOG)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_matrix_sku_catalog_origin_reject")
            return Response(status_code=403)
        store = deps.matrix_sku_catalog_store
        master_stores = deps.master_stores
        if store is None or master_stores is None:
            return Response(status_code=404)
        try:
            ms = await _load_snack_ms_by_code(deps)
        except Exception:
            _LOGGER.exception("admin_matrix_sku_catalog_ms_fail")
            return await _matrix_sku_catalog_page(
                request,
                deps,
                rows=(),
                error="Не удалось загрузить ассортимент МойСклад",
                status_code=502,
            )
        body = (await read_admin_body(request, deps)).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        action = (parsed.get("action") or [""])[-1].strip()
        if action != "bulk_save":
            rows = build_matrix_sku_catalog_rows(ms, store.list_all())
            return await _matrix_sku_catalog_page(
                request,
                deps,
                rows=rows,
                error="unknown action",
                status_code=400,
            )
        codes = list(parsed.get("product_code") or [])
        names = list(parsed.get("display_name") or [])
        capacities = list(parsed.get("capacity") or [])
        multipliers = list(parsed.get("product_multiplier") or [])
        if not (len(codes) == len(names) == len(capacities) == len(multipliers)):
            rows = build_matrix_sku_catalog_rows(ms, store.list_all())
            return await _matrix_sku_catalog_page(
                request,
                deps,
                rows=rows,
                error="mismatched form lists",
                status_code=400,
            )
        bulk_rows: list[BulkSaveMatrixSkuRow] = []
        try:
            for code, name, capacity_raw, multiplier_raw in zip(
                codes, names, capacities, multipliers, strict=True
            ):
                capacity_text = capacity_raw.strip()
                capacity = 0 if capacity_text == "" else int(capacity_text)
                mult_text = multiplier_raw.strip()
                multiplier = parse_sheet_decimal(mult_text) if mult_text else Decimal("1")
                bulk_rows.append(
                    BulkSaveMatrixSkuRow(
                        product_code=code,
                        display_name=name,
                        capacity=capacity,
                        product_multiplier=multiplier,
                    )
                )
        except ValueError, InvalidOperation:
            rows = build_matrix_sku_catalog_rows(ms, store.list_all())
            return await _matrix_sku_catalog_page(
                request,
                deps,
                rows=rows,
                error="invalid capacity or product_multiplier",
                status_code=400,
            )
        try:

            def _run() -> None:
                BulkSaveMatrixSku(
                    catalog=store,
                    audit_stores=master_stores,
                    now_factory=deps.now_factory,
                    product_multiplier_min=deps.matrix_multiplier_min,
                    product_multiplier_max=deps.matrix_multiplier_max,
                ).execute(
                    BulkSaveMatrixSkuInput(
                        rows=tuple(bulk_rows),
                        allowed_codes=frozenset(ms.keys()),
                        actor_telegram_user_id=actor,
                    )
                )

            await asyncio.to_thread(_run)
        except MatrixSkuCommandRejected as exc:
            _LOGGER.info(
                "admin_matrix_sku_catalog_reject",
                extra={"reason": exc.code, "action": action},
            )
            rows = build_matrix_sku_catalog_rows(ms, store.list_all())
            return await _matrix_sku_catalog_page(
                request,
                deps,
                rows=rows,
                error=exc.message,
                status_code=400,
            )
        return RedirectResponse(_MATRIX_SKU_CATALOG_PATH, status_code=303)


async def _matrix_sku_catalog_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    rows: tuple[MatrixSkuListRow, ...],
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    if deps.matrix_sku_catalog_store is None:
        return Response(status_code=404)
    return _TEMPLATES.TemplateResponse(
        request,
        "matrix_sku_catalog.html",
        page_context(
            request,
            deps,
            rows=rows,
            error=error,
        ),
        status_code=status_code,
    )


async def _load_snack_ms_by_code(deps: AdminHttpDeps) -> dict[str, tuple[str, bool]]:
    reader = deps.snack_sku_assortment_reader
    if reader is None:
        # ADR-0083: no live Remap in app — enrolled Mongo catalog only (no ERROR/502).
        store = deps.matrix_sku_catalog_store
        if store is None:
            return {}
        return {
            entry.product_code: (entry.display_name, False)
            for entry in store.list_all()
            if entry.product_code
        }
    entries = await reader.list_by_folder_ids(
        entity_kind="product",
        folder_ids=deps.snack_sku_folder_ids,
    )
    return {entry.code: (entry.name, bool(entry.archived)) for entry in entries if entry.code}


async def _layout_known_product_codes(deps: AdminHttpDeps) -> frozenset[str]:
    if deps.sku_catalog_master_enabled:
        ms = await _load_snack_ms_by_code(deps)
        return frozenset(ms)
    catalog = deps.provider.product_catalog_or_none()
    return frozenset(catalog.by_code.keys()) if catalog is not None else frozenset()
