from __future__ import annotations

import asyncio

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import MasterDataStores
from src.application.micromarket_loading import (
    AssemblyOrderRejected,
    LaunchFromAssemblyOrders,
    LaunchMicromarketLoading,
    LaunchRejected,
    LoadingDisabled,
    ManageMicromarketAssemblyOrders,
    MicromarketMoveGateway,
)
from src.domain.micromarket_loading.assembly_order import MicromarketAssemblyOrder
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import origin_allowed, read_admin_body, require_panel
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.routes.micromarket_loading_assembly_tab import _render_assembly_page
from src.interfaces.admin.routes.micromarket_loading_orders import (
    _render_assembly_print_html,
    _render_loading_page,
)
from src.interfaces.admin.routes.micromarket_loading_support import (
    _assembly_lines_from_form,
    _assembly_manage_error,
    _assembly_order_lines_from_form,
    _catalog_names,
    _DisabledMoveGateway,
    _fridge_workspace_url,
    _require_micromarket_machine,
)
from src.interfaces.admin.user_facing_errors import admin_error_present


@beartype
def register_micromarket_loading_assembly_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
) -> None:
    @router.post("/machines/{machine_id}/micromarket-assembly-orders")
    async def micromarket_assembly_order_create_post(
        request: Request,
        machine_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        assembly_store = deps.micromarket_assembly_order_store
        if assembly_store is None:
            return Response(status_code=503)
        body = await read_admin_body(request, deps)
        lines = _assembly_lines_from_form(body.decode("utf-8"), deps)
        result = await asyncio.to_thread(
            ManageMicromarketAssemblyOrders(
                store=assembly_store,
                warehouse_stock=deps.micromarket_warehouse_stock_snapshot,
                clock=deps.now_factory,
            ).create,
            machine_code=machine.machine_id.value,
            lines=lines,
        )
        if isinstance(result, MicromarketAssemblyOrder):
            return RedirectResponse(
                url=_fridge_workspace_url(
                    machine.machine_id.value,
                    "loading",
                    order_id=result.order_id,
                ),
                status_code=303,
            )
        admin_error = _assembly_manage_error(result)
        from src.interfaces.admin.routes.micromarket_planogram import _path_allowed_codes

        path_allowed_codes = await _path_allowed_codes(deps)
        return await asyncio.to_thread(
            _render_assembly_page,
            request,
            deps,
            stores,
            machine,
            message=None,
            admin_error=admin_error,
            path_allowed_codes=path_allowed_codes,
        )

    @router.post("/machines/{machine_id}/micromarket-assembly-orders/{order_id}/update")
    async def micromarket_assembly_order_update_post(
        request: Request,
        machine_id: str,
        order_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        assembly_store = deps.micromarket_assembly_order_store
        if assembly_store is None:
            return Response(status_code=503)
        body = await read_admin_body(request, deps)
        lines = _assembly_order_lines_from_form(body.decode("utf-8"))
        result = await asyncio.to_thread(
            ManageMicromarketAssemblyOrders(
                store=assembly_store,
                warehouse_stock=deps.micromarket_warehouse_stock_snapshot,
                clock=deps.now_factory,
            ).update,
            order_id=order_id,
            lines=lines,
        )
        if isinstance(result, MicromarketAssemblyOrder):
            return RedirectResponse(
                url=_fridge_workspace_url(
                    machine.machine_id.value,
                    "loading",
                    order_id=result.order_id,
                ),
                status_code=303,
            )
        admin_error = _assembly_manage_error(result)
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
            selected_order_id=order_id,
        )

    @router.post("/machines/{machine_id}/micromarket-assembly-orders/{order_id}/cancel")
    async def micromarket_assembly_order_cancel_post(
        request: Request,
        machine_id: str,
        order_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        assembly_store = deps.micromarket_assembly_order_store
        if assembly_store is None:
            return Response(status_code=503)
        result = await asyncio.to_thread(
            ManageMicromarketAssemblyOrders(
                store=assembly_store,
                warehouse_stock=deps.micromarket_warehouse_stock_snapshot,
                clock=deps.now_factory,
            ).cancel,
            order_id=order_id,
        )
        admin_error = _assembly_manage_error(result)
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
            selected_order_id=order_id,
        )

    @router.get("/machines/{machine_id}/micromarket-assembly-orders/{order_id}/print")
    async def micromarket_assembly_order_print_get(
        request: Request,
        machine_id: str,
        order_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        machine = _require_micromarket_machine(stores, machine_id)
        if machine is None:
            return Response(status_code=404)
        assembly_store = deps.micromarket_assembly_order_store
        if assembly_store is None:
            return Response(status_code=503)
        order = await asyncio.to_thread(assembly_store.get, order_id)
        if order is None or order.machine_code != machine.machine_id.value:
            return Response(status_code=404)
        return Response(
            content=_render_assembly_print_html(
                machine=machine,
                display_name=machine_profile_display_name(stores, machine),
                order=order,
                catalog_names=_catalog_names(deps),
            ),
            media_type="text/html; charset=utf-8",
        )

    @router.post("/machines/{machine_id}/micromarket-assembly-orders/load")
    async def micromarket_assembly_orders_load_post(
        request: Request,
        machine_id: str,
    ) -> Response:
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
        assembly_store = deps.micromarket_assembly_order_store
        if cycle_store is None or assembly_store is None:
            return Response(status_code=503)
        if (
            deps.micromarket_loading_execute_enabled
            and deps.micromarket_loading_move_gateway is None
        ):
            return Response(status_code=503)
        gateway: MicromarketMoveGateway = (
            deps.micromarket_loading_move_gateway or _DisabledMoveGateway()
        )
        launch = LaunchMicromarketLoading(
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
        )
        result = await asyncio.to_thread(
            LaunchFromAssemblyOrders(
                assembly_store=assembly_store,
                cycle_store=cycle_store,
                warehouse_stock=deps.micromarket_warehouse_stock_snapshot,
                launch=launch,
            ).execute,
            machine_code=machine.machine_id.value,
            actor=str(actor),
        )
        admin_error = None
        if isinstance(result, LoadingDisabled):
            admin_error = admin_error_present(result.message or "loading_disabled")
        elif isinstance(result, AssemblyOrderRejected):
            admin_error = admin_error_present(result.reason, targets=result.targets)
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
