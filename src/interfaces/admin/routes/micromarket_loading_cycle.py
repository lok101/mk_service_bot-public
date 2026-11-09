from __future__ import annotations

import asyncio

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import MasterDataStores
from src.application.micromarket_loading import (
    LaunchMicromarketLoading,
    LaunchRejected,
    LoadingDisabled,
    MicromarketMoveGateway,
    OpsAcceptMicromarketLoading,
    RollbackMicromarketLoading,
    SaveMicromarketLoadingDraft,
)
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import origin_allowed, read_admin_body, require_panel
from src.interfaces.admin.routes.micromarket_loading_orders import _render_loading_page
from src.interfaces.admin.routes.micromarket_loading_support import (
    _actor_may_ops_accept,
    _cycle_is_open,
    _DisabledMoveGateway,
    _draft_lines_from_form,
    _fridge_workspace_url,
    _require_micromarket_machine,
)
from src.interfaces.admin.user_facing_errors import admin_error_present


@beartype
def register_micromarket_loading_cycle_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
) -> None:
    @router.get("/machines/{machine_id}/micromarket-loading")
    async def micromarket_loading_get(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        if deps.micromarket_planogram_store is None or deps.micromarket_stock_store is None:
            return Response(status_code=404)
        return RedirectResponse(
            url=_fridge_workspace_url(machine_id, "assembly"),
            status_code=303,
        )

    @router.post("/machines/{machine_id}/micromarket-loading")
    async def micromarket_loading_launch_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        if deps.micromarket_planogram_store is None or deps.micromarket_stock_store is None:
            return Response(status_code=404)
        cycle_store = deps.micromarket_loading_cycle_store
        if cycle_store is None:
            return Response(status_code=503)
        if (
            deps.micromarket_loading_execute_enabled
            and deps.micromarket_loading_move_gateway is None
        ):
            return Response(status_code=503)
        body = await read_admin_body(request, deps)
        if not _cycle_is_open(cycle_store, machine.machine_id.value):
            lines = _draft_lines_from_form(body.decode("utf-8"))
            await asyncio.to_thread(
                SaveMicromarketLoadingDraft(cycle_store=cycle_store).execute,
                machine_code=machine.machine_id.value,
                lines=lines,
            )
        gateway: MicromarketMoveGateway = (
            deps.micromarket_loading_move_gateway or _DisabledMoveGateway()
        )
        result = await asyncio.to_thread(
            LaunchMicromarketLoading(
                cycle_store=cycle_store,
                stock_store=deps.micromarket_stock_store,
                gateway=gateway,
                execute_enabled=deps.micromarket_loading_execute_enabled,
                warehouse_gate_enabled=deps.micromarket_loading_warehouse_gate_enabled,
                timezone=deps.timezone,
                day_end_hour=deps.day_end_hour,
                clock=deps.now_factory,
                products=deps.domain_product_store,
                ensure_open_visit=deps.ensure_open_visit_task,
                warehouse_stock=deps.micromarket_warehouse_stock_snapshot,
            ).execute,
            machine_code=machine.machine_id.value,
        )
        admin_error = None
        if isinstance(result, LoadingDisabled):
            admin_error = admin_error_present(result.message or "loading_disabled")
        elif isinstance(result, LaunchRejected):
            admin_error = admin_error_present(result.reason)
        if admin_error is None:
            return RedirectResponse(
                url=_fridge_workspace_url(machine.machine_id.value, "loading"),
                status_code=303,
            )
        from src.interfaces.admin.routes.micromarket_planogram import _path_allowed_codes

        path_allowed_codes = await _path_allowed_codes(deps)
        return await asyncio.to_thread(
            _render_loading_page,
            request,
            deps,
            stores,
            machine,
            message=None,
            admin_error=admin_error,
            path_allowed_codes=path_allowed_codes,
        )

    @router.post("/machines/{machine_id}/micromarket-loading/ops-accept")
    async def micromarket_loading_ops_accept_post(
        request: Request,
        machine_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if not _actor_may_ops_accept(deps, actor):
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        cycle_store = deps.micromarket_loading_cycle_store
        stock_store = deps.micromarket_stock_store
        if cycle_store is None or stock_store is None:
            return Response(status_code=503)
        result = await asyncio.to_thread(
            OpsAcceptMicromarketLoading(
                cycle_store=cycle_store,
                stock_store=stock_store,
                planogram_store=deps.micromarket_planogram_store,
                publisher=deps.micromarket_shop_list_publisher,
                products=deps.domain_product_store,
                journal=deps.shop_list_publish_journal,
                baseline_store=deps.shop_list_baseline_store,
                now_factory=deps.now_factory,
            ).execute,
            machine_code=machine.machine_id.value,
            actor_id=str(actor),
        )
        if result.status == "rejected":
            from src.interfaces.admin.routes.micromarket_planogram import _path_allowed_codes
            from src.interfaces.admin.routes.micromarket_planograms import _render_fridge_workspace

            path_allowed_codes = await _path_allowed_codes(deps)
            return await asyncio.to_thread(
                _render_fridge_workspace,
                request,
                deps,
                stores,
                machine,
                active_tab="fm",
                path_allowed_codes=path_allowed_codes,
                message=None,
                admin_error=admin_error_present(result.reason or "ops_accept_rejected"),
            )
        return RedirectResponse(
            url=_fridge_workspace_url(machine.machine_id.value, "fm"),
            status_code=303,
        )

    @router.post("/machines/{machine_id}/micromarket-loading/rollback")
    async def micromarket_loading_rollback_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        cycle_store = deps.micromarket_loading_cycle_store
        gateway = deps.micromarket_loading_move_gateway
        if cycle_store is None or gateway is None:
            return Response(status_code=503)
        await asyncio.to_thread(
            RollbackMicromarketLoading(
                cycle_store=cycle_store,
                gateway=gateway,
                clock=deps.now_factory,
                detach_visit=deps.detach_visit_on_loading_rollback,
                warehouse_stock=deps.micromarket_warehouse_stock_snapshot,
                products=deps.domain_product_store,
            ).execute,
            machine_code=machine.machine_id.value,
        )
        return RedirectResponse(
            url=_fridge_workspace_url(machine.machine_id.value, "loading"),
            status_code=303,
        )
