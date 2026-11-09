from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from src.application.master_data import MasterDataStores, MasterMachine
from src.application.micromarket_loading import (
    AlreadyPublishing,
    Enqueued,
    MissingGroup,
    NothingToSend,
    PriceRequired,
    ShopListPublishTrigger,
    enqueue_micromarket_shop_list_publish,
)
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    origin_allowed,
    require_panel,
)
from src.interfaces.admin.planogram_publish_messages import (
    NOTHING_SENT_MICROMARKET,
    skipped_names_message_micromarket,
)
from src.interfaces.admin.routes.micromarket_planogram_access import (
    _path_allowed_codes,
    _require_micromarket_machine,
)
from src.interfaces.admin.routes.micromarket_planogram_context import _render_planogram_page

_LOGGER = logging.getLogger("src.interfaces.admin.routes.micromarket_planogram")


@beartype
def _wants_json_response(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "application/json" in accept.lower():
        return True
    requested_with = request.headers.get("x-requested-with", "")
    return requested_with.lower() == "xmlhttprequest"


@beartype
async def _publish_error_response(
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    error: str,
    path_allowed_codes: frozenset[str] | None,
    wants_json: bool,
    status_code: int = 200,
) -> Response:
    if wants_json:
        return JSONResponse({"ok": False, "error": error}, status_code=status_code)
    return await asyncio.to_thread(
        _render_planogram_page,
        request,
        deps,
        stores,
        machine,
        error=error,
        status_code=status_code,
        path_allowed_codes=path_allowed_codes,
    )


def register_micromarket_planogram_publish_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    assert stores is not None

    @router.post("/machines/{machine_id}/micromarket-planogram/publish")
    async def micromarket_planogram_publish(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_micromarket_planogram_publish_origin_reject")
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        store = deps.micromarket_planogram_store
        if store is None:
            return Response(status_code=404)
        path_allowed_codes = await _path_allowed_codes(deps)
        wants_json = _wants_json_response(request)
        publisher = deps.micromarket_shop_list_publisher
        if publisher is None:
            return await _publish_error_response(
                request,
                deps,
                stores,
                machine,
                error="Магазин Kit Shop для этого аппарата не найден",
                path_allowed_codes=path_allowed_codes,
                wants_json=wants_json,
            )

        def _enqueue() -> (
            AlreadyPublishing | Enqueued | MissingGroup | NothingToSend | PriceRequired
        ):
            return enqueue_micromarket_shop_list_publish(
                store=store,
                publisher=cast(Any, publisher),
                machine_code=machine_id,
                now=deps.now_factory(),
                products=deps.domain_product_store,
                stock_store=deps.micromarket_stock_store,
                journal=deps.shop_list_publish_journal,
                trigger=ShopListPublishTrigger.MANUAL,
                baseline_store=deps.shop_list_baseline_store,
            )

        result = await asyncio.to_thread(_enqueue)
        if isinstance(result, PriceRequired):
            return await _publish_error_response(
                request,
                deps,
                stores,
                machine,
                error=f"Укажите цену ≥ 1 ₽ для {result.product_code}",
                status_code=422,
                path_allowed_codes=path_allowed_codes,
                wants_json=wants_json,
            )
        if isinstance(result, MissingGroup):
            return await _publish_error_response(
                request,
                deps,
                stores,
                machine,
                error=f"kit_group_id required for {result.product_code}",
                status_code=422,
                path_allowed_codes=path_allowed_codes,
                wants_json=wants_json,
            )
        if isinstance(result, AlreadyPublishing):
            return await _publish_error_response(
                request,
                deps,
                stores,
                machine,
                error="Публикация уже идёт",
                path_allowed_codes=path_allowed_codes,
                wants_json=wants_json,
            )
        if isinstance(result, NothingToSend):
            return await _publish_error_response(
                request,
                deps,
                stores,
                machine,
                error=NOTHING_SENT_MICROMARKET,
                path_allowed_codes=path_allowed_codes,
                wants_json=wants_json,
            )
        notice: str | None = None
        if result.skipped_names:
            _LOGGER.info(
                "admin_planogram_publish_skipped",
                extra={"skipped_count": len(result.skipped_names)},
            )
            notice = skipped_names_message_micromarket(result.skipped_names)
        if wants_json:
            payload: dict[str, object] = {"ok": True}
            if notice is not None:
                payload["notice"] = notice
            return JSONResponse(payload)
        return await asyncio.to_thread(
            _render_planogram_page,
            request,
            deps,
            stores,
            machine,
            notice=notice,
            path_allowed_codes=path_allowed_codes,
        )
