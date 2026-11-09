from __future__ import annotations

from decimal import Decimal

from beartype import beartype
from fastapi import Request
from fastapi.responses import Response

from src.application.master_data import MasterDataStores, MasterMachine
from src.application.micromarket_loading import (
    GetMicromarketLoadingPreview,
    ResolveLoadingNeed,
    available_for_code,
    resolve_ms_catalog_code,
)
from src.domain.micromarket_loading.order import DraftLine, OrderStatus
from src.domain.micromarket_loading.quantities import need_qty
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.routes.micromarket_loading_rows import (
    _group_loading_sections,
    _loading_row_view,
    _loading_shelf_meta,
    _occupied_assembly_catalog_codes,
)
from src.interfaces.admin.routes.micromarket_loading_support import (
    _DRAFT_LAUNCH_STATUSES,
    _LOGGER,
    _UNGROUPED_SHELF_LABEL,
    _catalog_names,
)


@beartype
def _loading_tab_context(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    message: str | None,
    admin_error: object | None = None,
    fetch_warehouse: bool = True,
    can_ops_accept: bool = False,
) -> dict[str, object]:
    planogram_store = deps.micromarket_planogram_store
    stock_store = deps.micromarket_stock_store
    assert planogram_store is not None
    assert stock_store is not None
    preview = GetMicromarketLoadingPreview(
        planogram_store=planogram_store,
        stock_store=stock_store,
        catalog_names=_catalog_names(deps),
        products=deps.domain_product_store,
    ).execute(machine.machine_id.value)
    draft_by_code: dict[str, DraftLine] = {}
    order_open = False
    cycle_store = deps.micromarket_loading_cycle_store
    if cycle_store is not None:
        cycle = cycle_store.load(machine.machine_id.value)
        if cycle is not None:
            order_open = cycle.status is OrderStatus.OPEN
            if cycle.status in _DRAFT_LAUNCH_STATUSES:
                draft_by_code = {line.product_code: line for line in cycle.lines}
    assembly_store = deps.micromarket_assembly_order_store
    open_assembly_all = () if assembly_store is None else assembly_store.list_open()
    open_assembly_orders = tuple(
        order for order in open_assembly_all if order.machine_code == machine.machine_id.value
    )
    warehouse_by_product: dict[str, Decimal] | None = None
    if deps.micromarket_loading_execute_enabled and fetch_warehouse:
        catalog_codes: list[str] = []
        product_to_catalog: dict[str, str] = {}
        for row in preview.rows:
            catalog_code = resolve_ms_catalog_code(deps.domain_product_store, row.product_code)
            if catalog_code is None:
                continue
            product_to_catalog[row.product_code] = catalog_code
            catalog_codes.append(catalog_code)
        snapshot_store = deps.micromarket_warehouse_stock_snapshot
        if snapshot_store is not None:
            import time

            deadline = time.monotonic() + max(
                0,
                deps.micromarket_warehouse_stock_cold_wait_seconds,
            )
            snapshot = snapshot_store.get()
            while snapshot is None and time.monotonic() < deadline:
                time.sleep(0.25)
                snapshot = snapshot_store.get()
            if snapshot is None:
                _LOGGER.warning("micromarket_loading_preview_warehouse_snapshot_cold_timeout")
                warehouse_by_product = None
            elif not product_to_catalog:
                # No resolvable MS codes → degrade (—), not a dict of zeros (ISS-404).
                warehouse_by_product = None
            else:
                warehouse_by_product = {
                    product_code: available_for_code(
                        snapshot=snapshot,
                        open_orders=open_assembly_all,
                        catalog_code=catalog_code,
                    )
                    for product_code, catalog_code in product_to_catalog.items()
                    if catalog_code in snapshot.qty_by_catalog_code
                }
                if not warehouse_by_product:
                    # Snapshot has none of this planogram's codes (empty/stale) → degrade.
                    warehouse_by_product = None
        else:
            gateway = deps.micromarket_loading_move_gateway
            if gateway is not None:
                unique_catalog = list(dict.fromkeys(catalog_codes))
                if unique_catalog:
                    try:
                        warehouse_by_catalog = gateway.warehouse_qty_by_codes(unique_catalog)
                    except Exception as error:
                        _LOGGER.warning(
                            "micromarket_loading_preview_warehouse_batch_failed",
                            extra={"error": str(error)},
                        )
                        warehouse_by_catalog = None
                    if warehouse_by_catalog is not None:
                        warehouse_by_product = {
                            product_code: warehouse_by_catalog.get(catalog_code, Decimal("0"))
                            for product_code, catalog_code in product_to_catalog.items()
                        }
                else:
                    warehouse_by_product = None
    live_need_by_code = {
        row.product_code: need_qty(target_qty=row.target_qty, shelf_qty=row.stock_qty)
        for row in preview.rows
    }
    resolved_by_code: dict[str, tuple[Decimal, bool]] = {
        code: (qty, True) for code, qty in live_need_by_code.items()
    }
    supply_store = deps.micromarket_supply_order_store
    if supply_store is not None:
        for line in ResolveLoadingNeed(store=supply_store).execute(
            machine_id=machine.machine_id.value,
            live_need_by_code=live_need_by_code,
        ):
            resolved_by_code[line.product_code] = (line.need_qty, line.need_from_live)
    preview_group_ids = tuple(
        row.kit_group_id
        for row in preview.rows
        if isinstance(row.kit_group_id, int) and row.kit_group_id > 0
    )
    shelf_sort, shelf_titles, kit_names = _loading_shelf_meta(
        deps,
        machine.machine_id.value,
        preview_group_ids=preview_group_ids,
    )
    occupied_catalog = _occupied_assembly_catalog_codes(open_assembly_orders)
    rows = tuple(
        _loading_row_view(
            row,
            draft_by_code=draft_by_code,
            warehouse_by_product=warehouse_by_product,
            resolved_need=resolved_by_code[row.product_code][0],
            need_from_live=resolved_by_code[row.product_code][1],
            shelf_title=(
                shelf_titles.get(row.kit_group_id, "")
                if isinstance(row.kit_group_id, int) and row.kit_group_id > 0
                else _UNGROUPED_SHELF_LABEL
            ),
            shelf_sort_order=(
                shelf_sort.get(row.kit_group_id, 10**9)
                if isinstance(row.kit_group_id, int) and row.kit_group_id > 0
                else 10**9
            ),
            assembly_qty_locked=(
                (
                    resolve_ms_catalog_code(deps.domain_product_store, row.product_code)
                    or row.product_code
                )
                in occupied_catalog
            ),
        )
        for row in preview.rows
    )
    loading_sections = _group_loading_sections(rows, kit_names=kit_names)
    _LOGGER.info(
        "micromarket_loading_preview_viewed",
        extra={
            "machine_code": machine.machine_id.value,
            "sku_count": len(rows),
        },
    )
    return {
        "machine": machine,
        "display_name": machine_profile_display_name(stores, machine),
        "rows": rows,
        "loading_sections": loading_sections,
        "order_open": order_open,
        "can_ops_accept": can_ops_accept and order_open,
        "ops_accept_enabled": False,
        "message": message,
        "admin_error": admin_error,
        "error_target_codes": (
            tuple(getattr(admin_error, "targets", ())) if admin_error is not None else ()
        ),
        "assembly_orders": open_assembly_orders,
        "has_open_assembly_orders": bool(open_assembly_orders),
    }


@beartype
def _fm_tab_context(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    message: str | None,
    admin_error: object | None = None,
) -> dict[str, object]:
    order_open = False
    cycle_store = deps.micromarket_loading_cycle_store
    if cycle_store is not None:
        cycle = cycle_store.load(machine.machine_id.value)
        if cycle is not None:
            order_open = cycle.status is OrderStatus.OPEN
    assembly_store = deps.micromarket_assembly_order_store
    has_open_assembly_orders = False
    if assembly_store is not None:
        has_open_assembly_orders = any(
            order.machine_code == machine.machine_id.value for order in assembly_store.list_open()
        )
    return {
        "machine": machine,
        "display_name": machine_profile_display_name(stores, machine),
        "rows": (),
        "loading_sections": (),
        "order_open": order_open,
        "can_ops_accept": True,
        "ops_accept_enabled": order_open or has_open_assembly_orders,
        "message": message,
        "admin_error": admin_error,
        "error_target_codes": (
            tuple(getattr(admin_error, "targets", ())) if admin_error is not None else ()
        ),
        "assembly_order_summaries": (),
        "selected_assembly_order_id": None,
        "selected_assembly_order": None,
        "has_open_assembly_orders": has_open_assembly_orders,
    }


@beartype
def _render_assembly_page(
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    message: str | None,
    admin_error: object | None = None,
    path_allowed_codes: frozenset[str] | None = None,
) -> Response:
    from src.interfaces.admin.routes.micromarket_planograms import _render_fridge_workspace

    return _render_fridge_workspace(
        request,
        deps,
        stores,
        machine,
        active_tab="assembly",
        path_allowed_codes=path_allowed_codes,
        message=message,
        admin_error=admin_error,
    )
