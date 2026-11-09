from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qs, quote

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.micromarket_loading import (
    CopyMicromarketPlanogram,
    CopyMicromarketPlanogramInput,
    EmptyProcurementMirrorStore,
    InMemoryMicromarketMachineMultiplierStore,
    InMemoryMicromarketPriceChangeJournal,
    InMemoryMicromarketPricingRulesStore,
    InMemoryMicromarketProductMultiplierStore,
    MicromarketPlanogramCopyRejected,
    MicromarketResetLineResult,
    MicromarketResetPricesResult,
    ResetMicromarketPlanogramLinePrice,
    ResetMicromarketPlanogramPrices,
    SaveMicromarketPlanogram,
)
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    read_admin_body,
    require_panel,
)
from src.interfaces.admin.routes.micromarket_planogram_access import (
    _catalog_options,
    _path_allowed_codes,
    _require_micromarket_machine,
    _sellable_catalog_codes,
)
from src.interfaces.admin.routes.micromarket_planogram_context import _render_planogram_page
from src.interfaces.admin.routes.micromarket_planogram_parse import (
    _parse_planogram_form,
    _planogram_save_status,
    _submitted_form_best_effort,
)

_LOGGER = logging.getLogger("src.interfaces.admin.routes.micromarket_planogram")


@beartype
def _pricing_command_deps(deps: AdminHttpDeps) -> tuple[Any, ...]:
    planograms = deps.micromarket_planogram_store
    assert planograms is not None
    rules_store = deps.micromarket_pricing_rules_store or InMemoryMicromarketPricingRulesStore()
    product_mult = (
        deps.micromarket_product_multiplier_store or InMemoryMicromarketProductMultiplierStore()
    )
    machine_mult = (
        deps.micromarket_machine_multiplier_store or InMemoryMicromarketMachineMultiplierStore()
    )
    journal = deps.micromarket_price_change_journal or InMemoryMicromarketPriceChangeJournal()
    mirrors = deps.procurement_mirror_store or EmptyProcurementMirrorStore()
    return planograms, rules_store, product_mult, machine_mult, journal, mirrors


_RESET_DELTA_BLOCKED_NOTICE = (
    "Цена не сброшена: падение больше допустимого порога (запись в журнале)."
)


@beartype
def _planogram_reset_redirect_url(machine_id: str, *, delta_blocked: bool) -> str:
    url = f"/admin/micromarket-planograms/{machine_id}"
    if delta_blocked:
        return f"{url}?notice={quote(_RESET_DELTA_BLOCKED_NOTICE)}"
    return url


@beartype
def _reset_all_prices(deps: AdminHttpDeps, machine_id: str) -> MicromarketResetPricesResult:
    planograms, rules_store, product_mult, machine_mult, journal, mirrors = _pricing_command_deps(
        deps
    )
    return ResetMicromarketPlanogramPrices(
        planograms=planograms,
        rules_store=rules_store,
        product_multipliers=product_mult,
        machine_multipliers=machine_mult,
        mirrors=mirrors,
        journal=journal,
        products=deps.domain_product_store,
    ).execute(machine_code=machine_id)


@beartype
def _reset_one_price(
    deps: AdminHttpDeps, machine_id: str, product_code: str
) -> MicromarketResetLineResult:
    planograms, rules_store, product_mult, machine_mult, journal, mirrors = _pricing_command_deps(
        deps
    )
    return ResetMicromarketPlanogramLinePrice(
        planograms=planograms,
        rules_store=rules_store,
        product_multipliers=product_mult,
        machine_multipliers=machine_mult,
        mirrors=mirrors,
        journal=journal,
        products=deps.domain_product_store,
    ).execute(machine_code=machine_id, product_code=product_code)


def register_micromarket_planogram_mutation_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    assert stores is not None

    @router.get("/machines/{machine_id}/micromarket-planogram")
    async def micromarket_planogram_get(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        if deps.micromarket_planogram_store is None:
            return Response(status_code=404)
        return RedirectResponse(
            f"/admin/micromarket-planograms/{machine_id}",
            status_code=303,
        )

    @router.post("/machines/{machine_id}/micromarket-planogram")
    async def micromarket_planogram_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_micromarket_planogram_origin_reject")
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        store = deps.micromarket_planogram_store
        if store is None:
            return Response(status_code=404)
        body = (await read_admin_body(request, deps)).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        path_allowed_codes = await _path_allowed_codes(deps)
        try:
            shelves, lines = _parse_planogram_form(parsed)
        except ValueError as exc:
            submitted_shelves, submitted_lines = _submitted_form_best_effort(parsed)
            return await asyncio.to_thread(
                _render_planogram_page,
                request,
                deps,
                stores,
                machine,
                error=str(exc),
                submitted_lines=submitted_lines,
                submitted_shelves=submitted_shelves,
                status_code=_planogram_save_status(str(exc)),
                path_allowed_codes=path_allowed_codes,
            )
        catalog_codes = _sellable_catalog_codes(deps)
        catalog_names = {
            option.product_code: option.name
            for option in _catalog_options(deps, path_allowed_codes=path_allowed_codes)
        }
        try:

            def _save() -> None:
                SaveMicromarketPlanogram(
                    store=store,
                    catalog_codes=catalog_codes,
                    now_factory=deps.now_factory,
                    products=deps.domain_product_store,
                    stock_store=deps.micromarket_stock_store,
                    publisher=deps.micromarket_shop_list_publisher,
                    journal=deps.shop_list_publish_journal,
                    baseline_store=deps.shop_list_baseline_store,
                    price_journal=deps.micromarket_price_change_journal,
                    price_actor=str(actor),
                ).execute(
                    machine_code=machine_id,
                    lines=lines,
                    shelves=shelves,
                    catalog_names=catalog_names,
                )

            await asyncio.to_thread(_save)
        except ValueError as exc:
            message = str(exc)
            return await asyncio.to_thread(
                _render_planogram_page,
                request,
                deps,
                stores,
                machine,
                error=message,
                submitted_lines=lines,
                submitted_shelves=shelves,
                status_code=_planogram_save_status(message),
                path_allowed_codes=path_allowed_codes,
            )
        return RedirectResponse(
            f"/admin/micromarket-planograms/{machine_id}",
            status_code=303,
        )

    @router.post("/machines/{machine_id}/micromarket-planogram/reset-prices")
    async def micromarket_planogram_reset_prices(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None or deps.micromarket_planogram_store is None:
            return Response(status_code=404)
        result = await asyncio.to_thread(_reset_all_prices, deps, machine_id)
        return RedirectResponse(
            _planogram_reset_redirect_url(machine_id, delta_blocked=result.delta_blocked_count > 0),
            status_code=303,
        )

    @router.post("/machines/{machine_id}/micromarket-planogram/reset-price")
    async def micromarket_planogram_reset_price(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None or deps.micromarket_planogram_store is None:
            return Response(status_code=404)
        body = await read_admin_body(request, deps)
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        product_code = (parsed.get("product_code") or [""])[0].strip()
        delta_blocked = False
        if product_code:
            result = await asyncio.to_thread(_reset_one_price, deps, machine_id, product_code)
            delta_blocked = result.delta_blocked
        return RedirectResponse(
            _planogram_reset_redirect_url(machine_id, delta_blocked=delta_blocked),
            status_code=303,
        )

    @router.post("/machines/{machine_id}/micromarket-planogram/copy")
    async def micromarket_planogram_copy_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_micromarket_planogram_copy_origin_reject")
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        store = deps.micromarket_planogram_store
        if store is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        source_raw = fields.get("source_machine_id", "").strip()
        path_allowed_codes = await _path_allowed_codes(deps)

        async def _copy_error(message: str) -> Response:
            return await asyncio.to_thread(
                _render_planogram_page,
                request,
                deps,
                stores,
                machine,
                error=message,
                status_code=400,
                path_allowed_codes=path_allowed_codes,
            )

        if not source_raw:
            return await _copy_error("empty_copy_source")
        try:

            def _copy() -> None:
                CopyMicromarketPlanogram(
                    store=store,
                    machines=stores.machines,
                    now_factory=deps.now_factory,
                ).execute(
                    CopyMicromarketPlanogramInput(
                        source_machine_code=source_raw,
                        dest_machine_code=machine_id,
                    )
                )

            await asyncio.to_thread(_copy)
        except MicromarketPlanogramCopyRejected as exc:
            return await _copy_error(exc.code)
        return RedirectResponse(
            f"/admin/micromarket-planograms/{machine_id}",
            status_code=303,
        )
