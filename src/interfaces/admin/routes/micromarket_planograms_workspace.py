from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype
from fastapi import Request
from fastapi.responses import Response

from src.application.master_data import MasterDataStores, MasterMachine
from src.application.micromarket_loading import MicromarketPlanogramLine
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    page_context,
)
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.routes.micromarket_planograms_list import _tasks_feed_rows


@beartype
def _render_fridge_workspace(
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    active_tab: str,
    path_allowed_codes: frozenset[str] | None,
    status_code: int = 200,
    error: str | None = None,
    notice: str | None = None,
    submitted_lines: Sequence[MicromarketPlanogramLine] | None = None,
    message: str | None = None,
    admin_error: object | None = None,
    selected_order_id: str | None = None,
) -> Response:
    from src.interfaces.admin.routes.micromarket_loading import (
        _fm_tab_context,
        _loading_orders_tab_context,
        _loading_tab_context,
    )
    from src.interfaces.admin.routes.micromarket_planogram import _planogram_tab_context

    planogram_context = _planogram_tab_context(
        deps,
        stores,
        machine,
        error=error,
        notice=notice,
        submitted_lines=submitted_lines,
        path_allowed_codes=path_allowed_codes,
    )
    from src.interfaces.admin.http_common import session_user_id
    from src.interfaces.admin.routes.micromarket_loading import _actor_may_ops_accept

    user_id = session_user_id(request, deps)
    show_fm_tab = user_id is not None and _actor_may_ops_accept(deps, user_id)
    if active_tab == "fm" and not show_fm_tab:
        active_tab = "planogram"
    if active_tab == "assembly":
        loading_context = _loading_tab_context(
            deps,
            stores,
            machine,
            message=message,
            admin_error=admin_error,
            fetch_warehouse=True,
            can_ops_accept=show_fm_tab,
        )
    elif active_tab == "loading":
        loading_context = _loading_orders_tab_context(
            deps,
            stores,
            machine,
            message=message,
            admin_error=admin_error,
            selected_order_id=selected_order_id,
        )
    elif active_tab == "fm":
        loading_context = _fm_tab_context(
            deps,
            stores,
            machine,
            message=message,
            admin_error=admin_error,
        )
    else:
        loading_context = {
            "rows": (),
            "loading_sections": (),
            "order_open": False,
            "can_ops_accept": False,
            "ops_accept_enabled": False,
            "message": message,
            "admin_error": admin_error,
            "error_target_codes": (),
            "assembly_order_summaries": (),
            "selected_assembly_order_id": None,
            "selected_assembly_order": None,
            "has_open_assembly_orders": False,
        }
    journal_rows = (
        _tasks_feed_rows(
            deps,
            stores,
            machine_code=machine.machine_id.value,
        )
        if active_tab == "tasks"
        else ()
    )
    merged: dict[str, object] = {
        **planogram_context,
        **loading_context,
        "machine": machine,
        "display_name": machine_profile_display_name(stores, machine),
        "active_tab": active_tab,
        "show_fm_tab": show_fm_tab,
        "shop_list_publish_journal_rows": journal_rows,
    }
    return _TEMPLATES.TemplateResponse(
        request,
        "micromarket_fridge_workspace.html",
        page_context(request, deps, **merged),
        status_code=status_code,
    )
