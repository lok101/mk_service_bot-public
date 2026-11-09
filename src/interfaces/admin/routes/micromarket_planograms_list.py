from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype
from fastapi import Request
from fastapi.responses import Response

from src.application.master_data import MachineKind, MasterDataStores, MasterMachine
from src.application.micromarket_loading import (
    GetMicromarketLoadingPreview,
    ListMicromarketSupplyOrders,
    LiveNeedLine,
    LiveNeedMachine,
)
from src.application.reference_data import MsEntityKind
from src.domain.ids import MachineId
from src.domain.micromarket_loading.quantities import need_qty as calc_need_qty
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    page_context,
    planogram_static_context,
)
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.routes.micromarket_prices import (
    build_prices_tab_context,
    prices_tab_template_vars,
)

_LOGGER = logging.getLogger("src.interfaces.admin.routes.micromarket_planograms")


@beartype
@dataclass(frozen=True, slots=True)
class PlanogramListRow:
    machine_id: str
    display_name: str
    need_total: Decimal


@beartype
def _catalog_names(deps: AdminHttpDeps) -> dict[str, str]:
    catalog = deps.provider.product_catalog_or_none()
    if catalog is None:
        return {}
    return {
        code: entry.name
        for code, entry in catalog.by_code.items()
        if entry.entity_kind is MsEntityKind.PRODUCT
    }


@beartype
def _micromarket_machines(stores: MasterDataStores) -> tuple[MasterMachine, ...]:
    machines = [
        machine
        for machine in stores.machines.list_all()
        if machine.kind is MachineKind.MICRO_MARKET
    ]
    machines.sort(key=lambda item: item.machine_id.value)
    return tuple(machines)


@beartype
def _journal_display_name(stores: MasterDataStores, machine_code: str) -> str:
    machine = stores.machines.get(MachineId(machine_code))
    if machine is None:
        return machine_code
    return machine_profile_display_name(stores, machine)


@beartype
def _shop_list_publish_journal_rows(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    *,
    machine_code: str | None = None,
) -> tuple[dict[str, object], ...]:
    from src.application.micromarket_loading import (
        shop_list_publish_effects_detail_lines,
        shop_list_publish_effects_summary,
        shop_list_publish_trigger_label,
    )
    from src.interfaces.admin.clock_display import format_admin_moment

    journal = deps.shop_list_publish_journal
    if journal is None:
        return ()
    catalog_names = _catalog_names(deps)
    rows: list[dict[str, object]] = []
    for entry in journal.list_newest():
        if machine_code is not None and entry.machine_code != machine_code:
            continue
        summary = shop_list_publish_effects_summary(entry.effects)
        detail_lines = shop_list_publish_effects_detail_lines(
            entry.effects,
            catalog_names,
            intended_lines=entry.intended_lines,
            baseline_lines=entry.baseline_lines or None,
        )
        rows.append(
            {
                "kind": "publish",
                "sort_at": entry.created_at,
                "created_at_label": format_admin_moment(entry.created_at, deps.timezone),
                "display_name": _journal_display_name(stores, entry.machine_code),
                "machine_code": entry.machine_code,
                "trigger_label": shop_list_publish_trigger_label(entry.trigger),
                "effects_summary": summary if summary else "—",
                "effects_detail_lines": detail_lines,
                "status_label": entry.status.label_ru,
                "error_message": entry.error_message,
            }
        )
    return tuple(rows)


@beartype
def _loading_task_feed_rows(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    *,
    machine_code: str | None = None,
) -> tuple[dict[str, object], ...]:
    from src.application.micromarket_loading import project_loading_task_rows
    from src.domain.micromarket_loading.order import MicromarketLoadingCycle
    from src.interfaces.admin.clock_display import format_admin_moment

    cycle_store = deps.micromarket_loading_cycle_store
    if cycle_store is None:
        return ()
    list_cycles = getattr(cycle_store, "list_cycles", None)
    cycles: tuple[MicromarketLoadingCycle, ...]
    if callable(list_cycles):
        cycles = tuple(list_cycles())
    else:
        loaded: list[MicromarketLoadingCycle] = []
        for machine in _micromarket_machines(stores):
            cycle = cycle_store.load(machine.machine_id.value)
            if cycle is not None:
                loaded.append(cycle)
        cycles = tuple(loaded)
    rows: list[dict[str, object]] = []
    for row in project_loading_task_rows(
        cycles,
        machine_code=machine_code,
        timezone=deps.timezone,
    ):
        day_label = (
            row.opened_operational_day.isoformat()
            if row.opened_operational_day is not None
            else format_admin_moment(row.sort_at, deps.timezone)
        )
        rows.append(
            {
                "kind": "loading",
                "sort_at": row.sort_at,
                "created_at_label": day_label,
                "display_name": _journal_display_name(stores, row.machine_code),
                "machine_code": row.machine_code,
                "trigger_label": row.trigger_label,
                "effects_summary": row.effects_summary,
                "effects_detail_lines": list(row.effects_detail_lines),
                "status_label": row.status_label,
                "error_message": None,
            }
        )
    return tuple(rows)


@beartype
def _tasks_feed_sort_key(row: dict[str, object]) -> tuple[str, str]:
    from src.interfaces.admin.clock_display import admin_moment_sort_key

    sort_at = row["sort_at"]
    if not isinstance(sort_at, datetime):
        raise TypeError(f"tasks feed sort_at must be datetime, got {type(sort_at)!r}")
    return (admin_moment_sort_key(sort_at), str(row["machine_code"]))


@beartype
def _tasks_feed_rows(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    *,
    machine_code: str | None = None,
) -> tuple[dict[str, object], ...]:
    merged = [
        *_shop_list_publish_journal_rows(deps, stores, machine_code=machine_code),
        *_loading_task_feed_rows(deps, stores, machine_code=machine_code),
    ]
    # Journal created_at from Mongo is often naive UTC; loading sort_at is tz-aware.
    merged.sort(key=_tasks_feed_sort_key, reverse=True)
    return tuple(merged)


@beartype
def _live_need_machine(
    deps: AdminHttpDeps,
    machine: MasterMachine,
) -> LiveNeedMachine:
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
    lines = tuple(
        LiveNeedLine(
            product_code=row.product_code,
            need_qty=calc_need_qty(target_qty=row.target_qty, shelf_qty=row.stock_qty),
            shelf_qty=row.stock_qty,
            target_qty=Decimal(row.target_qty),
            name=row.name,
        )
        for row in preview.rows
    )
    return LiveNeedMachine(machine_id=machine.machine_id.value, lines=lines)


@beartype
def _supply_order_list_rows(
    deps: AdminHttpDeps,
) -> tuple[dict[str, str], ...]:
    from src.interfaces.admin.clock_display import format_admin_moment

    store = deps.micromarket_supply_order_store
    if store is None:
        return ()
    rows: list[dict[str, str]] = []
    for order in ListMicromarketSupplyOrders(store=store).execute():
        machine_count = str(len(order.machines))
        line_count = str(sum(len(machine.lines) for machine in order.machines))
        rows.append(
            {
                "order_id": order.order_id,
                "created_at_label": format_admin_moment(order.created_at, deps.timezone),
                "machine_count": machine_count,
                "line_count": line_count,
            },
        )
    return tuple(rows)


@beartype
def _render_planograms_list(
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    *,
    telegram_user_id: int,
    active_tab: str = "machines",
    create_error: str | None = None,
    auto_download_order_id: str | None = None,
    prices_error: str | None = None,
) -> Response:
    rows: list[PlanogramListRow] = []
    for machine in _micromarket_machines(stores):
        live = _live_need_machine(deps, machine)
        need_total = sum((line.need_qty for line in live.lines), Decimal("0"))
        rows.append(
            PlanogramListRow(
                machine_id=machine.machine_id.value,
                display_name=machine_profile_display_name(stores, machine),
                need_total=need_total,
            ),
        )
    journal_rows = _tasks_feed_rows(deps, stores)
    order_rows = _supply_order_list_rows(deps)
    prices_ctx = build_prices_tab_context(
        deps,
        telegram_user_id=telegram_user_id,
        error=prices_error,
    )
    _LOGGER.info(
        "micromarket_planograms_list_viewed",
        extra={"machine_count": len(rows), "active_tab": active_tab},
    )
    return _TEMPLATES.TemplateResponse(
        request,
        "micromarket_planograms.html",
        page_context(
            request,
            deps,
            rows=tuple(rows),
            active_tab=active_tab,
            shop_list_publish_journal_rows=journal_rows,
            supply_order_rows=order_rows,
            create_error=create_error,
            auto_download_order_id=auto_download_order_id,
            **planogram_static_context(),
            **prices_tab_template_vars(prices_ctx),
        ),
    )
