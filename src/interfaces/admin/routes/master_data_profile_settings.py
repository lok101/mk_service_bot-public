from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qs, quote

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import (
    MachineKind,
    MasterDataCommandRejected,
    UpdateMachineSettings,
    UpdateMachineSettingsInput,
)
from src.domain.ids import MachineId
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    origin_allowed,
    page_context,
    read_admin_body,
    require_panel,
)
from src.interfaces.admin.page_builders import build_machine_profile_page_sync
from src.interfaces.admin.routes.coffee_equipment import catalog_error_text, equipment_catalogs
from src.interfaces.admin.routes.master_data_park import _refresh_provider_master_data

_LOGGER = logging.getLogger(__name__)
_PROFILE_TABS = frozenset({"monitoring", "equipment"})


@beartype
def _resolve_profile_tab(raw: str | None) -> str:
    tab = (raw or "").strip()
    if tab in _PROFILE_TABS:
        return tab
    return "monitoring"


@beartype
def _profile_redirect(machine_id: str, *, tab: str, error: str | None = None) -> RedirectResponse:
    query = f"tab={quote(tab)}"
    if error is not None:
        query = f"error={quote(error)}&{query}"
    return RedirectResponse(f"/admin/machines/{machine_id}?{query}", status_code=303)


@beartype
def register_master_data_profile_settings_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    assert stores is not None

    @router.get("/machines/{machine_id}")
    async def machine_profile_get(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        page = await asyncio.to_thread(
            build_machine_profile_page_sync,
            deps,
            stores,
            machine_id,
            ms_names_by_code=None,
        )
        if page is None:
            return Response(status_code=404)
        catalogs = equipment_catalogs(deps)

        def _catalog_view() -> tuple[
            tuple[object, ...],
            tuple[object, ...],
            tuple[object, ...],
            bool,
        ]:
            if catalogs is None or page.machine.kind is not MachineKind.COFFEE:
                return (), (), (), False
            selected_id = page.machine.coffee_machine_model_id or ""
            selected = catalogs.models.get(selected_id)
            return (
                catalogs.models.list_all(),
                catalogs.stand_types.list_all(),
                catalogs.stand_colors.list_all(),
                selected is not None and selected.floor_standing,
            )

        coffee_models, stand_types, stand_colors, hide_stands = await asyncio.to_thread(
            _catalog_view,
        )
        active_tab = _resolve_profile_tab(request.query_params.get("tab"))
        return _TEMPLATES.TemplateResponse(
            request,
            "machine_profile.html",
            page_context(
                request,
                deps,
                machine=page.machine,
                display_name=page.display_name,
                company_name=page.company_name,
                coffee_models=coffee_models,
                stand_types=stand_types,
                stand_colors=stand_colors,
                hide_stands=hide_stands,
                active_tab=active_tab,
                error=catalog_error_text(request.query_params.get("error")),
            ),
        )

    @router.post("/machines/{machine_id}")
    async def machine_profile_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        body = (await read_admin_body(request, deps)).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        fields = {key: values[-1] for key, values in parsed.items()}
        mid = MachineId(machine_id)
        machine = stores.machines.get(mid)
        if machine is None:
            return Response(status_code=404)
        active_tab = _resolve_profile_tab(request.query_params.get("tab"))

        try:

            def _update_settings() -> None:
                catalog_keys = (
                    "coffee_machine_model_id",
                    "stand_type_id",
                    "stand_color_id",
                )
                catalogs = equipment_catalogs(deps)
                posted_catalog = any(fields.get(key, "").strip() for key in catalog_keys)
                apply_catalogs = catalogs is not None and (
                    machine.kind is MachineKind.COFFEE or posted_catalog
                )
                UpdateMachineSettings(
                    stores=stores,
                    now_factory=deps.now_factory,
                    catalogs=catalogs,
                ).execute(
                    UpdateMachineSettingsInput(
                        machine_id=mid,
                        include_in_no_sales_monitoring=("include_in_no_sales_monitoring" in fields),
                        create_visit_on_no_sales="create_visit_on_no_sales" in fields,
                        include_in_visit_photo_review=("include_in_visit_photo_review" in fields),
                        actor_telegram_user_id=actor,
                        coffee_machine_model_id=fields.get("coffee_machine_model_id", "").strip()
                        or None,
                        stand_type_id=fields.get("stand_type_id", "").strip() or None,
                        stand_color_id=fields.get("stand_color_id", "").strip() or None,
                        apply_equipment_catalogs=apply_catalogs,
                    )
                )

            await asyncio.to_thread(_update_settings)
        except MasterDataCommandRejected as exc:
            if exc.code == "machine_not_found":
                return Response(status_code=404)
            return _profile_redirect(machine_id, tab="equipment", error=exc.code)

        try:
            await asyncio.to_thread(_refresh_provider_master_data, deps)
        except Exception:
            _LOGGER.exception("admin_master_data_hydrate_failed")
            return Response(status_code=500)
        return _profile_redirect(machine_id, tab=active_tab)
