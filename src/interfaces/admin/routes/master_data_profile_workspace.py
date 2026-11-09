from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import replace

from beartype import beartype
from fastapi import Request
from fastapi.responses import Response

from src.application.inventory_reconciliation import resolve_current_company_name
from src.application.master_data import MasterDataStores, MasterMachine
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    page_context,
    planogram_static_context,
)
from src.interfaces.admin.machine_layout_view import (
    LayoutProductOption,
    SnackPlanogramProfileView,
    build_planogram_slots,
    build_planogram_view_from_submitted_fields,
    layout_product_options_json,
    merge_domain_product_slot_fields,
)
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.page_builders import (
    _auto_sync_allowed_for_layout,
    _layout_autocomplete_product_options,
    build_machine_planogram_page_sync,
)
from src.interfaces.admin.planogram_product_options import planogram_product_options
from src.interfaces.admin.routes.matrix_catalog import _load_snack_ms_by_code

_LOGGER = logging.getLogger(__name__)
_PLANOGRAM_MAIN_CLASS = "admin-main--full-width"


@beartype
def _domain_product_picker_context(deps: AdminHttpDeps) -> dict[str, object]:
    store = deps.domain_product_store
    if store is None:
        return {
            "planogram_show_create": False,
            "planogram_product_options_json": "[]",
        }
    options = planogram_product_options(store)
    payload = [
        {
            "domain_product_id": option.domain_product_id,
            "name": option.name,
            "number": option.number,
            "linked": option.linked,
        }
        for option in options
    ]
    return {
        "planogram_show_create": True,
        "planogram_product_options_json": json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).replace("<", "\\u003c"),
    }


@beartype
def _enrich_layout_section_with_products(
    deps: AdminHttpDeps,
    *,
    machine: MasterMachine,
    layout_section: SnackPlanogramProfileView,
) -> SnackPlanogramProfileView:
    layout_store = deps.snack_layout_store
    products = deps.domain_product_store
    if layout_store is None or products is None:
        return layout_section
    layout = layout_store.get(machine.machine_id.value)
    if layout is None:
        return layout_section
    options_by_code = {opt.product_code: opt for opt in layout_section.product_options}
    resolved = build_planogram_slots(
        shelf_count=layout_section.shelf_count,
        slots_per_shelf=layout_section.slots_per_shelf,
        merges=layout.merges,
        cells=layout.cells,
        options_by_code=options_by_code,
        products=products,
    )
    return replace(
        layout_section,
        slots=merge_domain_product_slot_fields(
            slots=layout_section.slots,
            resolved=resolved,
        ),
    )


@beartype
async def _planogram_error_response(
    *,
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    machine_id: str,
    fields: dict[str, str],
    parsed_qs: Mapping[str, list[str]],
    layout_error: str,
    product_options: tuple[LayoutProductOption, ...],
    archived_product_codes: frozenset[str] = frozenset(),
) -> Response:
    product_codes = list(parsed_qs.get("planogram_product_code") or [])
    product_names = list(parsed_qs.get("planogram_product_name") or [])
    if len(product_names) < len(product_codes):
        product_names.extend([""] * (len(product_codes) - len(product_names)))
    domain_product_ids = list(parsed_qs.get("planogram_domain_product_id") or [])
    if len(domain_product_ids) < len(product_codes):
        domain_product_ids.extend([""] * (len(product_codes) - len(domain_product_ids)))
    layout_section = build_planogram_view_from_submitted_fields(
        machine=machine,
        machines=stores.machines,
        shelf_count_raw=fields.get("planogram_shelf_count", "6"),
        slots_per_shelf_raw=fields.get("planogram_slots_per_shelf", "10"),
        shelf_indices=list(parsed_qs.get("planogram_shelf_index") or []),
        slot_indices=list(parsed_qs.get("planogram_slot_index") or []),
        line_numbers=list(parsed_qs.get("planogram_line_number") or []),
        product_codes=product_codes,
        product_names=product_names,
        merge_shelves=list(parsed_qs.get("planogram_merge_shelf") or []),
        merge_slots=list(parsed_qs.get("planogram_merge_slot") or []),
        matrix_multiplier_raw=fields.get("matrix_multiplier", "1"),
        auto_sync_enabled="auto_sync_enabled" in fields,
        product_options=product_options,
        auto_sync_allowed=_auto_sync_allowed_for_layout(
            deps,
            machine_code=machine.machine_id.value,
        ),
        domain_product_ids=domain_product_ids,
        products=deps.domain_product_store,
    )
    display_name = machine_profile_display_name(stores, machine)
    company_name = ""
    occupancy_store = deps.company_occupancy_store
    if occupancy_store is not None:
        company_name = resolve_current_company_name(
            occupancy_store.list_for_machine(machine.machine_id),
            deps.company_display_names or {},
        )
    autocomplete_options = _layout_autocomplete_product_options(
        product_options,
        ms_names_by_code=None,
        archived_product_codes=archived_product_codes,
    )
    return _TEMPLATES.TemplateResponse(
        request,
        "machine_planogram.html",
        page_context(
            request,
            deps,
            main_class=_PLANOGRAM_MAIN_CLASS,
            machine=machine,
            display_name=display_name,
            company_name=company_name,
            layout_section=layout_section,
            layout_error=layout_error,
            layout_archived_warning=None,
            layout_autocomplete_product_options=autocomplete_options,
            layout_autocomplete_options_json=layout_product_options_json(autocomplete_options),
            **_domain_product_picker_context(deps),
            **planogram_static_context(),
        ),
        status_code=400,
    )


@beartype
async def render_machine_planogram_workspace(
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine_id: str,
    *,
    layout_error: str | None = None,
    status_code: int = 200,
) -> Response:
    ms_names: dict[str, tuple[str, bool]] | None = None
    if deps.sku_catalog_master_enabled:
        try:
            ms_names = await _load_snack_ms_by_code(deps)
        except Exception:
            _LOGGER.exception("admin_layout_known_ms_fail")
    page = await asyncio.to_thread(
        build_machine_planogram_page_sync,
        deps,
        stores,
        machine_id,
        ms_names_by_code=ms_names,
    )
    if page is None:
        return Response(status_code=404)
    layout_section = _enrich_layout_section_with_products(
        deps,
        machine=page.machine,
        layout_section=page.layout_section,
    )
    error = layout_error if layout_error is not None else request.query_params.get("layout_error")
    return _TEMPLATES.TemplateResponse(
        request,
        "machine_planogram.html",
        page_context(
            request,
            deps,
            main_class=_PLANOGRAM_MAIN_CLASS,
            machine=page.machine,
            display_name=page.display_name,
            company_name=page.company_name,
            layout_section=layout_section,
            layout_error=error,
            layout_archived_warning=page.layout_archived_warning,
            layout_autocomplete_product_options=page.layout_autocomplete_product_options,
            layout_autocomplete_options_json=page.layout_autocomplete_options_json,
            **_domain_product_picker_context(deps),
            **planogram_static_context(),
        ),
        status_code=status_code,
    )
