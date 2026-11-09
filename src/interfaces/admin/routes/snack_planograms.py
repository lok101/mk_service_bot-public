from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import Response

from src.application.master_data import MachineKind, MasterDataStores, MasterMachine
from src.domain.ids import MachineId
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    page_context,
    require_panel,
)
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.system_users_view import _snack_screen_mounted


@beartype
@dataclass(frozen=True, slots=True)
class SnackPlanogramListRow:
    machine_id: str
    display_name: str


@beartype
def register_snack_planograms_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    stores = deps.master_stores
    assert stores is not None

    @router.get("/snack-planograms")
    async def snack_planograms_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not _snack_screen_mounted(deps):
            return Response(status_code=404)
        return _render_snack_planograms_list(request, deps, stores)

    @router.get("/snack-planograms/{machine_id}")
    async def snack_planogram_workspace_get(request: Request, machine_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.MICROMARKET_PLANOGRAMS)
        if isinstance(actor, Response):
            return actor
        if not _snack_screen_mounted(deps):
            return Response(status_code=404)
        machine = stores.machines.get(MachineId(machine_id))
        if machine is None or machine.kind is not MachineKind.SNACK:
            return Response(status_code=404)
        from src.interfaces.admin.routes.master_data_profile import (
            render_machine_planogram_workspace,
        )

        return await render_machine_planogram_workspace(request, deps, stores, machine_id)


@beartype
def _snack_machines(stores: MasterDataStores) -> tuple[MasterMachine, ...]:
    machines = [
        machine for machine in stores.machines.list_all() if machine.kind is MachineKind.SNACK
    ]
    machines.sort(key=lambda item: item.machine_id.value)
    return tuple(machines)


@beartype
def _render_snack_planograms_list(
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
) -> Response:
    rows = tuple(
        SnackPlanogramListRow(
            machine_id=machine.machine_id.value,
            display_name=machine_profile_display_name(stores, machine),
        )
        for machine in _snack_machines(stores)
    )
    return _TEMPLATES.TemplateResponse(
        request,
        "snack_planograms.html",
        page_context(request, deps, rows=rows),
    )
