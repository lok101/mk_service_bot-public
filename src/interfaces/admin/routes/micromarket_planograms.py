from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import MachineKind
from src.application.micromarket_loading import (
    DeleteMicromarketSupplyOrder,
    SupplyOrderNotFound,
)
from src.domain.ids import MachineId
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    origin_allowed,
    read_admin_body,
    require_panel,
)
from src.interfaces.admin.routes.micromarket_planograms_list import (
    _live_need_machine,
    _render_planograms_list,
)
from src.interfaces.admin.routes.micromarket_planograms_orders import (
    _create_supply_order,
    _download_supply_order,
)
from src.interfaces.admin.routes.micromarket_planograms_workspace import (
    _render_fridge_workspace,
)
from src.interfaces.admin.routes.micromarket_prices import (
    redirect_prices,
    save_micromarket_prices_from_form,
)

__all__ = [
    "register_micromarket_planograms_routes",
    "_render_fridge_workspace",
    "_live_need_machine",
]


@beartype
def register_micromarket_planograms_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    assert stores is not None

    @router.get("/micromarket-planograms")
    async def micromarket_planograms_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if deps.micromarket_planogram_store is None or deps.micromarket_stock_store is None:
            return Response(status_code=404)
        tab = request.query_params.get("tab")
        if tab == "tasks":
            active_tab = "tasks"
        elif tab == "orders":
            active_tab = "orders"
        elif tab == "prices":
            active_tab = "prices"
        else:
            active_tab = "machines"
        auto_download = (request.query_params.get("download") or "").strip() or None
        notice = (request.query_params.get("notice") or "").strip() or None
        prices_error = (request.query_params.get("prices_error") or "").strip() or None
        return await asyncio.to_thread(
            _render_planograms_list,
            request,
            deps,
            stores,
            telegram_user_id=actor,
            active_tab=active_tab,
            auto_download_order_id=auto_download,
            create_error=notice,
            prices_error=prices_error,
        )

    @router.post("/micromarket-planograms/prices")
    async def micromarket_planograms_prices_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MATRIX_PRICING)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        body = await read_admin_body(request, deps)
        error = await asyncio.to_thread(save_micromarket_prices_from_form, deps, body=body)
        return redirect_prices(error=error)

    @router.post("/micromarket-planograms/orders")
    async def micromarket_planograms_create_order(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if (
            deps.micromarket_planogram_store is None
            or deps.micromarket_stock_store is None
            or deps.micromarket_supply_order_store is None
        ):
            return Response(status_code=404)
        body = await read_admin_body(request, deps)
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        selected_ids = [value.strip() for value in parsed.get("machine_id", []) if value.strip()]
        arrival_raw = (parsed.get("expected_arrival_at") or [""])[0].strip()
        return await asyncio.to_thread(
            _create_supply_order,
            deps,
            stores,
            selected_ids,
            arrival_raw,
        )

    @router.get("/micromarket-planograms/orders/{order_id}/download")
    async def micromarket_planograms_download_order(request: Request, order_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        store = deps.micromarket_supply_order_store
        if store is None:
            return Response(status_code=404)
        return await asyncio.to_thread(_download_supply_order, store, order_id)

    @router.post("/micromarket-planograms/orders/{order_id}/delete")
    async def micromarket_planograms_delete_order(request: Request, order_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        store = deps.micromarket_supply_order_store
        if store is None:
            return Response(status_code=404)
        result = await asyncio.to_thread(
            DeleteMicromarketSupplyOrder(store=store).execute,
            order_id,
        )
        if isinstance(result, SupplyOrderNotFound):
            return Response(status_code=404)
        return RedirectResponse(
            url="/admin/micromarket-planograms?tab=orders",
            status_code=303,
        )

    @router.get("/micromarket-planograms/{machine_id}")
    async def micromarket_fridge_workspace_get(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if deps.micromarket_planogram_store is None or deps.micromarket_stock_store is None:
            return Response(status_code=404)
        machine = stores.machines.get(MachineId(machine_id))
        if machine is None or machine.kind is not MachineKind.MICRO_MARKET:
            return Response(status_code=404)
        tab = request.query_params.get("tab")
        if tab == "loading":
            active_tab = "loading"
        elif tab == "assembly":
            active_tab = "assembly"
        elif tab == "tasks":
            active_tab = "tasks"
        elif tab == "fm":
            active_tab = "fm"
        else:
            active_tab = "planogram"
        selected_order_id = request.query_params.get("order") or None
        path_allowed_codes = None
        if active_tab == "planogram":
            from src.interfaces.admin.routes.micromarket_planogram import _path_allowed_codes

            path_allowed_codes = await _path_allowed_codes(deps)
        notice = request.query_params.get("notice") or None
        return await asyncio.to_thread(
            _render_fridge_workspace,
            request,
            deps,
            stores,
            machine,
            active_tab=active_tab,
            path_allowed_codes=path_allowed_codes,
            notice=notice,
            selected_order_id=selected_order_id,
        )
