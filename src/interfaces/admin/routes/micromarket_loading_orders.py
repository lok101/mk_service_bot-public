from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype
from fastapi import Request
from fastapi.responses import Response

from src.application.master_data import MasterDataStores, MasterMachine
from src.application.micromarket_loading import available_for_code
from src.domain.micromarket_loading.assembly_order import MicromarketAssemblyOrder
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.micromarket_loading_support import (
    _LAUNCH_STEPPER_MAX,
    _catalog_names,
    _loading_cycle_order_open,
    _qty_display,
)


@beartype
@dataclass(frozen=True, slots=True)
class AssemblyOrderSummaryView:
    order_id: str
    created_display: str
    position_count: int


@beartype
@dataclass(frozen=True, slots=True)
class AssemblyOrderLineEditView:
    catalog_code: str
    name: str
    warehouse_qty_display: str
    qty: Decimal
    stepper_max: int


@beartype
@dataclass(frozen=True, slots=True)
class AssemblyOrderDetailView:
    order_id: str
    created_display: str
    lines: tuple[AssemblyOrderLineEditView, ...]


@beartype
def _assembly_order_summaries(
    orders: Sequence[MicromarketAssemblyOrder],
    timezone: ZoneInfo,
) -> tuple[AssemblyOrderSummaryView, ...]:
    from src.interfaces.admin.clock_display import admin_moment_sort_key, format_admin_moment

    sorted_orders = sorted(
        orders,
        key=lambda order: admin_moment_sort_key(order.created_at),
        reverse=True,
    )
    return tuple(
        AssemblyOrderSummaryView(
            order_id=order.order_id,
            created_display=format_admin_moment(order.created_at, timezone),
            position_count=len(order.lines),
        )
        for order in sorted_orders
    )


@beartype
def _assembly_order_detail_view(
    deps: AdminHttpDeps,
    order: MicromarketAssemblyOrder,
    *,
    open_orders: Sequence[MicromarketAssemblyOrder],
) -> AssemblyOrderDetailView:
    from src.interfaces.admin.clock_display import format_admin_moment

    catalog_names = _catalog_names(deps)
    snapshot = None
    snapshot_store = deps.micromarket_warehouse_stock_snapshot
    if snapshot_store is not None:
        snapshot = snapshot_store.get()
    line_views: list[AssemblyOrderLineEditView] = []
    for line in order.lines:
        warehouse_qty: Decimal | None = None
        if snapshot is not None:
            warehouse_qty = available_for_code(
                snapshot=snapshot,
                open_orders=tuple(open_orders),
                catalog_code=line.catalog_code,
            )
        stepper_max = max(
            _LAUNCH_STEPPER_MAX,
            int(line.qty.to_integral_value()),
            int((warehouse_qty or Decimal("0")).to_integral_value()),
        )
        line_views.append(
            AssemblyOrderLineEditView(
                catalog_code=line.catalog_code,
                name=catalog_names.get(line.catalog_code, line.catalog_code),
                warehouse_qty_display=_qty_display(warehouse_qty),
                qty=line.qty,
                stepper_max=stepper_max,
            )
        )
    return AssemblyOrderDetailView(
        order_id=order.order_id,
        created_display=format_admin_moment(order.created_at, deps.timezone),
        lines=tuple(line_views),
    )


@beartype
def _loading_orders_tab_context(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    message: str | None,
    selected_order_id: str | None,
    admin_error: object | None = None,
) -> dict[str, object]:
    del stores
    assembly_store = deps.micromarket_assembly_order_store
    open_orders = () if assembly_store is None else assembly_store.list_open()
    machine_orders = tuple(
        order for order in open_orders if order.machine_code == machine.machine_id.value
    )
    summaries = _assembly_order_summaries(machine_orders, deps.timezone)
    selected_id = selected_order_id
    if selected_id is None and summaries:
        selected_id = summaries[0].order_id
    detail: AssemblyOrderDetailView | None = None
    if selected_id is not None:
        for order in machine_orders:
            if order.order_id == selected_id:
                detail = _assembly_order_detail_view(deps, order, open_orders=open_orders)
                break
    return {
        "assembly_order_summaries": summaries,
        "selected_assembly_order_id": selected_id,
        "selected_assembly_order": detail,
        "has_open_assembly_orders": bool(summaries),
        "order_open": _loading_cycle_order_open(deps, machine.machine_id.value),
        "message": message,
        "admin_error": admin_error,
        "error_target_codes": (
            tuple(getattr(admin_error, "targets", ())) if admin_error is not None else ()
        ),
    }


@beartype
def _render_loading_page(
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    message: str | None,
    admin_error: object | None = None,
    path_allowed_codes: frozenset[str] | None = None,
    selected_order_id: str | None = None,
) -> Response:
    from src.interfaces.admin.routes.micromarket_planograms import _render_fridge_workspace

    return _render_fridge_workspace(
        request,
        deps,
        stores,
        machine,
        active_tab="loading",
        path_allowed_codes=path_allowed_codes,
        message=message,
        admin_error=admin_error,
        selected_order_id=selected_order_id,
    )


@beartype
def _render_assembly_print_html(
    *,
    machine: MasterMachine,
    display_name: str,
    order: MicromarketAssemblyOrder,
    catalog_names: Mapping[str, str],
) -> str:
    rows = "".join(
        (
            "<tr>"
            f"<td>{line.catalog_code}</td>"
            f"<td>{catalog_names.get(line.catalog_code, line.catalog_code)}</td>"
            f"<td>{_qty_display(line.qty)}</td>"
            "</tr>"
        )
        for line in order.lines
    )
    return (
        "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
        f"<title>Сборка {machine.machine_id.value}</title>"
        "<style>body{font-family:sans-serif;margin:1.5rem}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #333;padding:0.4rem;text-align:left}"
        "@media print{button{display:none}}</style></head><body>"
        f"<h1>Ордер сборки {machine.machine_id.value}</h1>"
        f"<p>{display_name}</p>"
        f"<p>order_id={order.order_id}</p>"
        "<table><thead><tr><th>Код</th><th>Имя</th><th>Кол-во</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<p><button onclick='window.print()'>Печать</button></p>"
        "</body></html>"
    )
