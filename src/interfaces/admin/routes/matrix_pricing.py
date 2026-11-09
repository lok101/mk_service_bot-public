from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, InvalidOperation

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.matrix_automation import BaseMarginCommandRejected, SaveBaseMargin
from src.application.shared import parse_sheet_decimal
from src.domain.matrix_pricing import calculate_sell_price
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
from src.interfaces.admin.matrix_pricing_form import (
    base_margin_params_from_form,
    form_values_from_base_margin,
    matrix_pricing_rejection_message,
)

_LOGGER = logging.getLogger(__name__)
_MATRIX_PRICING_PATH = "/admin/matrix-pricing"

__all__ = ["register_matrix_pricing_routes"]


@beartype
def register_matrix_pricing_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    @router.get("/matrix-pricing")
    async def matrix_pricing_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MATRIX_PRICING)
        if isinstance(actor, Response):
            return actor
        return _matrix_pricing_page(request, deps)

    @router.post("/matrix-pricing")
    async def matrix_pricing_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MATRIX_PRICING)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_matrix_pricing_origin_reject")
            return Response(status_code=403)
        store = deps.matrix_base_margin_store
        master_stores = deps.master_stores
        if store is None or master_stores is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        try:
            params = base_margin_params_from_form(fields)
        except ValueError as exc:
            return _matrix_pricing_page(
                request,
                deps,
                error=str(exc),
                status_code=400,
                form_override=fields,
            )
        try:

            def _run() -> None:
                SaveBaseMargin(
                    store=store,
                    audit_stores=master_stores,
                    now_factory=deps.now_factory,
                    scale_price_min_bound=deps.scale_price_min_bound,
                    scale_price_max_bound=deps.scale_price_max_bound,
                    scale_rate_min_bound=deps.scale_rate_min_bound,
                    scale_rate_max_bound=deps.scale_rate_max_bound,
                    curvature_min=deps.curvature_min,
                    curvature_max=deps.curvature_max,
                    margin_floor_min=deps.margin_floor_min,
                    margin_floor_max=deps.margin_floor_max,
                ).execute(params=params, actor_telegram_user_id=actor)

            await asyncio.to_thread(_run)
        except BaseMarginCommandRejected as exc:
            _LOGGER.info(
                "admin_matrix_pricing_reject",
                extra={"reason": exc.code},
            )
            return _matrix_pricing_page(
                request,
                deps,
                error=matrix_pricing_rejection_message(code=exc.code, fallback=exc.message),
                status_code=400,
                form_override=fields,
            )
        return RedirectResponse(_MATRIX_PRICING_PATH, status_code=303)


def _matrix_pricing_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    error: str | None = None,
    status_code: int = 200,
    form_override: dict[str, str] | None = None,
) -> Response:
    store = deps.matrix_base_margin_store
    if store is None:
        return Response(status_code=404)
    params = store.get()
    if form_override is not None:
        form = {
            "scale_price_min": form_override.get("scale_price_min", ""),
            "scale_price_max": form_override.get("scale_price_max", ""),
            "scale_rate_max": form_override.get("scale_rate_max", ""),
            "scale_rate_min": form_override.get("scale_rate_min", ""),
            "curvature": form_override.get("curvature", ""),
            "margin_floor": form_override.get("margin_floor", ""),
            "rounding_last_digits": form_override.get("rounding_last_digits", ""),
        }
    elif params is None:
        form = {
            "scale_price_min": "",
            "scale_price_max": "",
            "scale_rate_max": "",
            "scale_rate_min": "",
            "curvature": "",
            "margin_floor": "",
            "rounding_last_digits": "",
        }
    else:
        form = form_values_from_base_margin(params)
    preview_purchase_raw = request.query_params.get("preview_purchase", "").strip()
    preview_sell: int | None = None
    if params is not None and preview_purchase_raw:
        try:
            purchase = parse_sheet_decimal(preview_purchase_raw)
            preview_sell = calculate_sell_price(
                purchase=purchase,
                product_multiplier=Decimal("1"),
                matrix_multiplier=Decimal("1"),
                params=params,
            )
        except InvalidOperation, ValueError:
            preview_sell = None
    return _TEMPLATES.TemplateResponse(
        request,
        "matrix_pricing.html",
        page_context(
            request,
            deps,
            form=form,
            empty_store=params is None,
            error=error,
            preview_purchase=preview_purchase_raw,
            preview_sell=preview_sell,
        ),
        status_code=status_code,
    )
