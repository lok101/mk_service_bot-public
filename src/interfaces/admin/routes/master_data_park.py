from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.inventory_reconciliation import resolve_current_company_name
from src.application.master_data import (
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
    MasterDataCommandRejected,
    MoveMachineToStorage,
    MoveMachineToStorageInput,
    PlaceMachineFromStorage,
    PlaceMachineFromStorageInput,
    RelocateMachine,
    RelocateMachineInput,
    UpdateLocationAttributes,
    UpdateLocationAttributesInput,
    hydrate_provider_from_master_data,
)
from src.application.reference_data import clear_location_roster_technician
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
    require_panel,
)
from src.interfaces.admin.master_data_view import (
    build_location_form_view,
    build_master_machines_view,
)

_LOGGER = logging.getLogger(__name__)
_MACHINES_PATH = "/admin/machines"


@beartype
def register_master_data_park_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    assert stores is not None

    @router.get("/machines")
    async def machines_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        company_names: dict[MachineId, str] = {}
        occupancy_store = deps.company_occupancy_store
        if occupancy_store is not None:
            display_names = deps.company_display_names or {}
            for machine in stores.machines.list_all():
                company_names[machine.machine_id] = resolve_current_company_name(
                    occupancy_store.list_for_machine(machine.machine_id),
                    display_names,
                )
        view = build_master_machines_view(stores, company_names=company_names)
        return _TEMPLATES.TemplateResponse(
            request,
            "master_machines.html",
            page_context(request, deps, rows=view.rows),
        )

    @router.get("/machines/install")
    async def install_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        return _TEMPLATES.TemplateResponse(
            request,
            "master_install.html",
            page_context(request, deps),
        )

    @router.post("/machines/install")
    async def install_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        try:

            def _install() -> None:
                InstallMachineAtLocation(
                    stores=stores,
                    now_factory=deps.now_factory,
                    export_hook=deps.master_data_export_hook,
                ).execute(
                    InstallMachineAtLocationInput(
                        name=fields.get("name", "").strip(),
                        city=fields.get("city", "").strip(),
                        street=fields.get("street", "").strip(),
                        house=fields.get("house", "").strip(),
                        latitude=_optional_decimal(fields.get("latitude", "")),
                        longitude=_optional_decimal(fields.get("longitude", "")),
                        kind=_parse_kind(fields.get("kind", "")),
                        actor_telegram_user_id=actor,
                    )
                )

            await asyncio.to_thread(_install)
        except (MasterDataCommandRejected, ValueError) as exc:
            return _TEMPLATES.TemplateResponse(
                request,
                "master_install.html",
                page_context(
                    request,
                    deps,
                    error=str(exc),
                    name=fields.get("name", ""),
                    city=fields.get("city", ""),
                    street=fields.get("street", ""),
                    house=fields.get("house", ""),
                    kind=fields.get("kind", "coffee"),
                    latitude=fields.get("latitude", ""),
                    longitude=fields.get("longitude", ""),
                ),
                status_code=400,
            )
        try:
            await asyncio.to_thread(_refresh_provider_master_data, deps)
        except Exception:
            _LOGGER.exception("admin_master_data_hydrate_failed")
            return Response(status_code=500)
        return RedirectResponse(_MACHINES_PATH, status_code=303)

    @router.get("/machines/{machine_id}/relocate")
    async def relocate_get(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        return _TEMPLATES.TemplateResponse(
            request,
            "master_relocate.html",
            page_context(request, deps, machine_id=machine_id),
        )

    @router.post("/machines/{machine_id}/relocate")
    async def relocate_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        try:

            def _relocate() -> None:
                RelocateMachine(
                    stores=stores,
                    now_factory=deps.now_factory,
                    export_hook=deps.master_data_export_hook,
                ).execute(
                    RelocateMachineInput(
                        machine_id=MachineId(machine_id),
                        name=fields.get("name", "").strip(),
                        city=fields.get("city", "").strip(),
                        street=fields.get("street", "").strip(),
                        house=fields.get("house", "").strip(),
                        latitude=_optional_decimal(fields.get("latitude", "")),
                        longitude=_optional_decimal(fields.get("longitude", "")),
                        actor_telegram_user_id=actor,
                    )
                )

            await asyncio.to_thread(_relocate)
        except (MasterDataCommandRejected, ValueError) as exc:
            return _TEMPLATES.TemplateResponse(
                request,
                "master_relocate.html",
                page_context(
                    request,
                    deps,
                    error=str(exc),
                    machine_id=machine_id,
                    name=fields.get("name", ""),
                    city=fields.get("city", ""),
                    street=fields.get("street", ""),
                    house=fields.get("house", ""),
                    latitude=fields.get("latitude", ""),
                    longitude=fields.get("longitude", ""),
                ),
                status_code=400,
            )

        def _clear_roster_tech() -> None:
            clear_location_roster_technician(
                MachineId(machine_id),
                applied=deps.roster_store,
                draft=deps.roster_draft_store,
                actor_telegram_user_id=actor,
                now=deps.now_factory(),
            )

        await asyncio.to_thread(_clear_roster_tech)
        try:
            await asyncio.to_thread(_refresh_provider_master_data, deps)
        except Exception:
            _LOGGER.exception("admin_master_data_hydrate_failed")
            return Response(status_code=500)
        return RedirectResponse(_MACHINES_PATH, status_code=303)

    @router.post("/machines/{machine_id}/storage")
    async def storage_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        try:

            def _storage() -> None:
                MoveMachineToStorage(
                    stores=stores,
                    now_factory=deps.now_factory,
                    export_hook=deps.master_data_export_hook,
                ).execute(
                    MoveMachineToStorageInput(
                        machine_id=MachineId(machine_id),
                        actor_telegram_user_id=actor,
                    )
                )

            await asyncio.to_thread(_storage)
        except MasterDataCommandRejected:
            return Response(status_code=400)
        try:
            await asyncio.to_thread(_refresh_provider_master_data, deps)
        except Exception:
            _LOGGER.exception("admin_master_data_hydrate_failed")
            return Response(status_code=500)
        return RedirectResponse(_MACHINES_PATH, status_code=303)

    @router.get("/machines/{machine_id}/place")
    async def place_get(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        return _TEMPLATES.TemplateResponse(
            request,
            "master_place.html",
            page_context(request, deps, machine_id=machine_id, create_new_location=True),
        )

    @router.post("/machines/{machine_id}/place")
    async def place_post(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        create_new = bool(fields.get("create_new_location"))
        location_id_raw = fields.get("location_id", "").strip() or None
        try:

            def _place() -> None:
                PlaceMachineFromStorage(
                    stores=stores,
                    now_factory=deps.now_factory,
                    export_hook=deps.master_data_export_hook,
                ).execute(
                    PlaceMachineFromStorageInput(
                        machine_id=MachineId(machine_id),
                        name=fields.get("name", "").strip(),
                        city=fields.get("city", "").strip(),
                        street=fields.get("street", "").strip(),
                        house=fields.get("house", "").strip(),
                        latitude=_optional_decimal(fields.get("latitude", "")),
                        longitude=_optional_decimal(fields.get("longitude", "")),
                        create_new_location=create_new,
                        location_id=None if create_new else location_id_raw,
                        actor_telegram_user_id=actor,
                    )
                )

            await asyncio.to_thread(_place)
        except (MasterDataCommandRejected, ValueError) as exc:
            return _TEMPLATES.TemplateResponse(
                request,
                "master_place.html",
                page_context(
                    request,
                    deps,
                    error=str(exc),
                    machine_id=machine_id,
                    create_new_location=create_new,
                    location_id=fields.get("location_id", ""),
                    name=fields.get("name", ""),
                    city=fields.get("city", ""),
                    street=fields.get("street", ""),
                    house=fields.get("house", ""),
                    latitude=fields.get("latitude", ""),
                    longitude=fields.get("longitude", ""),
                ),
                status_code=400,
            )
        try:
            await asyncio.to_thread(_refresh_provider_master_data, deps)
        except Exception:
            _LOGGER.exception("admin_master_data_hydrate_failed")
            return Response(status_code=500)
        return RedirectResponse(_MACHINES_PATH, status_code=303)

    @router.get("/locations/{location_id}")
    async def location_get(request: Request, location_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        view = build_location_form_view(stores, location_id)
        if view is None:
            return Response(status_code=404)
        return _TEMPLATES.TemplateResponse(
            request,
            "master_location.html",
            page_context(request, deps, location=view),
        )

    @router.post("/locations/{location_id}")
    async def location_post(request: Request, location_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        try:

            def _update_location() -> None:
                UpdateLocationAttributes(
                    stores=stores,
                    now_factory=deps.now_factory,
                    export_hook=deps.master_data_export_hook,
                ).execute(
                    UpdateLocationAttributesInput(
                        location_id=location_id,
                        name=fields.get("name", "").strip(),
                        city=fields.get("city", "").strip(),
                        street=fields.get("street", "").strip(),
                        house=fields.get("house", "").strip(),
                        latitude=_optional_decimal(fields.get("latitude", "")),
                        longitude=_optional_decimal(fields.get("longitude", "")),
                        actor_telegram_user_id=actor,
                    )
                )

            await asyncio.to_thread(_update_location)
        except (MasterDataCommandRejected, ValueError) as exc:
            view = build_location_form_view(stores, location_id)
            if view is None:
                return Response(status_code=404)
            return _TEMPLATES.TemplateResponse(
                request,
                "master_location.html",
                page_context(request, deps, location=view, error=str(exc)),
                status_code=400,
            )
        try:
            await asyncio.to_thread(_refresh_provider_master_data, deps)
        except Exception:
            _LOGGER.exception("admin_master_data_hydrate_failed")
            return Response(status_code=500)
        return RedirectResponse(f"/admin/locations/{location_id}", status_code=303)


def _optional_decimal(raw: str) -> Decimal | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return parse_sheet_decimal(text)
    except ValueError as exc:
        raise ValueError(f"invalid decimal: {raw!r}") from exc


def _parse_kind(raw: str) -> MachineKind:
    normalized = raw.strip().lower()
    if normalized == MachineKind.SNACK.value:
        return MachineKind.SNACK
    if normalized == MachineKind.COFFEE.value:
        return MachineKind.COFFEE
    if normalized == MachineKind.MICRO_MARKET.value:
        return MachineKind.MICRO_MARKET
    raise ValueError(f"unknown machine kind: {raw!r}")


def _refresh_provider_master_data(deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    if stores is None:
        return
    hydrate_provider_from_master_data(deps.provider, stores)
