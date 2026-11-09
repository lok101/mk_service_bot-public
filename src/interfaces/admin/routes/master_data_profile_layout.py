from __future__ import annotations

import asyncio
import logging
from decimal import InvalidOperation
from urllib.parse import parse_qs, quote

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import MachineKind
from src.application.matrix_automation import (
    ApplySnackMatrixRejected,
    CopySnackLayout,
    CopySnackLayoutInput,
    SaveSnackLayout,
    SnackLayoutCommandRejected,
)
from src.application.shared import parse_sheet_decimal
from src.domain.ids import MachineId
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    page_context,
    planogram_static_context,
    read_admin_body,
    require_panel,
)
from src.interfaces.admin.machine_layout_view import (
    LayoutFormParseError,
    LayoutProductOption,
    build_layout_product_options,
    build_save_snack_layout_input_from_parsed_planogram,
    name_index_from_options,
    parse_planogram_form,
)
from src.interfaces.admin.page_builders import build_machine_planogram_page_sync
from src.interfaces.admin.planogram_publish_messages import NOTHING_SENT, skipped_names_message
from src.interfaces.admin.routes.master_data_park import _refresh_provider_master_data
from src.interfaces.admin.routes.master_data_profile_workspace import (
    _PLANOGRAM_MAIN_CLASS,
    _domain_product_picker_context,
    _enrich_layout_section_with_products,
    _planogram_error_response,
)
from src.interfaces.admin.routes.matrix_catalog import (
    _layout_known_product_codes,
    _load_snack_ms_by_code,
)
from src.interfaces.admin.system_users_view import _snack_screen_mounted

_LOGGER = logging.getLogger(__name__)


async def _build_layout_product_options(
    deps: AdminHttpDeps,
) -> tuple[LayoutProductOption, ...]:
    known = await _layout_known_product_codes(deps)
    ms_names: dict[str, str] = {}
    catalog_by_code: dict[str, tuple[str, int]] = {}
    if deps.sku_catalog_master_enabled:
        ms = await _load_snack_ms_by_code(deps)
        ms_names = {code: name for code, (name, _archived) in ms.items()}
        store = deps.matrix_sku_catalog_store
        if store is not None:
            for entry in store.list_all():
                catalog_by_code[entry.product_code] = (entry.display_name, entry.capacity)
    else:
        catalog = deps.provider.product_catalog_or_none()
        if catalog is not None:
            ms_names = {code: entry.name for code, entry in catalog.by_code.items()}
    return build_layout_product_options(
        known_codes=known, ms_names=ms_names, catalog_by_code=catalog_by_code
    )


def _layout_apply_error_message(code: str) -> str:
    if code == "base_margin_not_loaded":
        return "Шкала наценки не задана"
    return NOTHING_SENT if code == "nothing_to_send" else code


@beartype
def register_master_data_profile_layout_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    assert stores is not None

    @router.get("/machines/{machine_id}/layout")
    async def machine_planogram_get(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not _snack_screen_mounted(deps):
            return Response(status_code=404)
        machine = stores.machines.get(MachineId(machine_id))
        if machine is None or machine.kind is not MachineKind.SNACK:
            return Response(status_code=404)
        return RedirectResponse(f"/admin/snack-planograms/{machine_id}", status_code=303)

    @router.post("/machines/{machine_id}/layout")
    async def machine_planogram_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if not deps.layout_master_enabled or deps.snack_layout_store is None:
            return Response(status_code=404)
        body = (await read_admin_body(request, deps)).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        fields = {key: values[-1] for key, values in parsed.items()}
        mid = MachineId(machine_id)
        machine = stores.machines.get(mid)
        if machine is None or machine.kind is not MachineKind.SNACK:
            return Response(status_code=404)

        try:
            layout_known = await _layout_known_product_codes(deps)
            product_options = await _build_layout_product_options(deps)
            archived_product_codes: frozenset[str] = frozenset()
            if deps.sku_catalog_master_enabled:
                ms = await _load_snack_ms_by_code(deps)
                archived_product_codes = frozenset(
                    code for code, (_name, archived) in ms.items() if archived
                )
        except Exception:
            _LOGGER.exception("admin_layout_known_ms_fail")
            return Response(status_code=502)
        options_by_code = {opt.product_code: opt for opt in product_options}
        name_to_codes = name_index_from_options(product_options)
        product_codes = list(parsed.get("planogram_product_code") or [])
        product_names = list(parsed.get("planogram_product_name") or [])
        if len(product_names) < len(product_codes):
            product_names.extend([""] * (len(product_codes) - len(product_names)))
        domain_product_ids = list(parsed.get("planogram_domain_product_id") or [])
        if len(domain_product_ids) < len(product_codes):
            domain_product_ids.extend([""] * (len(product_codes) - len(domain_product_ids)))
        try:
            parsed_planogram = parse_planogram_form(
                shelf_count_raw=fields.get("planogram_shelf_count", "6"),
                slots_per_shelf_raw=fields.get("planogram_slots_per_shelf", "10"),
                shelf_indices=list(parsed.get("planogram_shelf_index") or []),
                slot_indices=list(parsed.get("planogram_slot_index") or []),
                line_numbers=list(parsed.get("planogram_line_number") or []),
                product_codes=product_codes,
                product_names=product_names,
                merge_shelves=list(parsed.get("planogram_merge_shelf") or []),
                merge_slots=list(parsed.get("planogram_merge_slot") or []),
                options_by_code=options_by_code,
                name_to_codes=name_to_codes,
                domain_product_ids=domain_product_ids,
            )
        except LayoutFormParseError as exc:
            return await _planogram_error_response(
                request=request,
                deps=deps,
                stores=stores,
                machine=machine,
                machine_id=machine_id,
                fields=fields,
                parsed_qs=parsed,
                layout_error=exc.code,
                product_options=product_options,
                archived_product_codes=archived_product_codes,
            )

        layout_store = deps.snack_layout_store
        assert layout_store is not None
        try:

            def _save_layout() -> None:
                multiplier_raw = fields.get("matrix_multiplier", "1").strip() or "1"
                snapshot_store = deps.matrix_price_snapshot_store
                if snapshot_store is None:
                    raise SnackLayoutCommandRejected(
                        "matrix price snapshot store is not configured",
                        code="layout_save_rejected",
                    )
                save_input = build_save_snack_layout_input_from_parsed_planogram(
                    machine_code=machine_id,
                    matrix_multiplier=parse_sheet_decimal(multiplier_raw),
                    auto_sync_enabled="auto_sync_enabled" in fields,
                    parsed=parsed_planogram,
                    actor_telegram_user_id=actor,
                )
                SaveSnackLayout(
                    layouts=layout_store,
                    audit_stores=stores,
                    now_factory=deps.now_factory,
                    known_product_codes=layout_known,
                    matrix_multiplier_min=deps.matrix_multiplier_min,
                    matrix_multiplier_max=deps.matrix_multiplier_max,
                    snapshots=snapshot_store,
                    archived_product_codes=archived_product_codes,
                    products=deps.domain_product_store,
                ).execute(save_input)

            await asyncio.to_thread(_save_layout)
        except (
            LayoutFormParseError,
            SnackLayoutCommandRejected,
            ValueError,
            InvalidOperation,
        ) as exc:
            code = getattr(exc, "code", "layout_save_rejected")
            return await _planogram_error_response(
                request=request,
                deps=deps,
                stores=stores,
                machine=machine,
                machine_id=machine_id,
                fields=fields,
                parsed_qs=parsed,
                layout_error=code,
                product_options=product_options,
                archived_product_codes=archived_product_codes,
            )

        try:
            await asyncio.to_thread(_refresh_provider_master_data, deps)
        except Exception:
            _LOGGER.exception("admin_master_data_hydrate_failed")
            return Response(status_code=500)
        return RedirectResponse(f"/admin/snack-planograms/{machine_id}", status_code=303)

    @router.post("/machines/{machine_id}/layout/copy")
    async def machine_layout_copy_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not deps.layout_master_enabled or deps.snack_layout_store is None:
            return Response(status_code=404)
        if not origin_allowed(request):
            return Response(status_code=403)
        dest = stores.machines.get(MachineId(machine_id))
        if dest is None or dest.kind is not MachineKind.SNACK:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        source_raw = fields.get("source_machine_id", "").strip()

        async def _layout_copy_error_response(layout_error: str) -> Response:
            page = await asyncio.to_thread(
                build_machine_planogram_page_sync,
                deps,
                stores,
                machine_id,
                ms_names_by_code=None,
            )
            if page is None:
                return Response(status_code=404)
            layout_section = _enrich_layout_section_with_products(
                deps,
                machine=page.machine,
                layout_section=page.layout_section,
            )
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
                    layout_error=layout_error,
                    layout_archived_warning=page.layout_archived_warning,
                    layout_autocomplete_product_options=page.layout_autocomplete_product_options,
                    layout_autocomplete_options_json=page.layout_autocomplete_options_json,
                    **_domain_product_picker_context(deps),
                    **planogram_static_context(),
                ),
                status_code=400,
            )

        if not source_raw:
            return await _layout_copy_error_response("empty_copy_source")
        layout_store = deps.snack_layout_store
        assert layout_store is not None
        try:
            known = await _layout_known_product_codes(deps)
        except Exception:
            _LOGGER.exception("admin_layout_known_ms_fail")
            return Response(status_code=502)
        try:

            def _copy() -> None:
                CopySnackLayout(
                    layouts=layout_store,
                    machines=stores.machines,
                    audit_stores=stores,
                    now_factory=deps.now_factory,
                    known_product_codes=known,
                ).execute(
                    CopySnackLayoutInput(
                        source_machine_code=source_raw,
                        dest_machine_code=machine_id,
                        actor_telegram_user_id=actor,
                    )
                )

            await asyncio.to_thread(_copy)
        except SnackLayoutCommandRejected as exc:
            return await _layout_copy_error_response(exc.code)
        return RedirectResponse(f"/admin/snack-planograms/{machine_id}", status_code=303)

    @router.post("/machines/{machine_id}/layout/apply")
    async def machine_layout_apply_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if deps.apply_snack_matrix is None:
            return Response(status_code=404)
        machine = stores.machines.get(MachineId(machine_id))
        if machine is None or machine.kind is not MachineKind.SNACK:
            return Response(status_code=404)
        try:

            def _apply() -> object:
                return deps.apply_snack_matrix.execute(  # type: ignore[union-attr]
                    machine_code=machine_id,
                    actor_telegram_user_id=actor,
                )

            result = await asyncio.to_thread(_apply)
        except ApplySnackMatrixRejected as exc:
            message = _layout_apply_error_message(exc.code)
            return RedirectResponse(
                f"/admin/snack-planograms/{machine_id}?layout_error={quote(message)}",
                status_code=303,
            )
        skipped = getattr(result, "skipped_names", ())
        if skipped:
            message = skipped_names_message(tuple(skipped))
            return RedirectResponse(
                f"/admin/snack-planograms/{machine_id}?layout_error={quote(message)}",
                status_code=303,
            )
        return RedirectResponse(f"/admin/snack-planograms/{machine_id}", status_code=303)
