from __future__ import annotations

import json
import logging

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from src.application.shared import (
    AdminNavStructureInvalid,
    admin_nav_structure_to_raw,
    default_admin_nav_structure,
    merge_mounted_panels_for_editor,
    parse_admin_nav_structure,
)
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
from src.interfaces.admin.system_users_view import mounted_admin_panels

_LOGGER = logging.getLogger(__name__)
_NAV_SETTINGS_PATH = "/admin/nav-settings"

__all__ = ["register_nav_settings_routes"]


@beartype
def register_nav_settings_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    @router.get("/nav-settings")
    async def nav_settings_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.NAV_SETTINGS)
        if isinstance(actor, Response):
            return actor
        return _nav_settings_page(request, deps)

    @router.post("/nav-settings")
    async def nav_settings_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.NAV_SETTINGS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_nav_settings_origin_reject")
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        raw = fields.get("structure_json", "")
        try:
            data = json.loads(raw)
            structure = parse_admin_nav_structure(data)
        except json.JSONDecodeError, AdminNavStructureInvalid, TypeError, ValueError:
            return PlainTextResponse("Invalid nav structure", status_code=400)
        if deps.admin_nav_structure_store is None:
            return PlainTextResponse("Nav store unavailable", status_code=500)
        deps.admin_nav_structure_store.save(structure)
        return RedirectResponse(_NAV_SETTINGS_PATH, status_code=303)


def _nav_settings_page(request: Request, deps: AdminHttpDeps) -> Response:
    structure = None
    if deps.admin_nav_structure_store is not None:
        structure = deps.admin_nav_structure_store.get()
    if structure is None:
        structure = default_admin_nav_structure()
    structure = merge_mounted_panels_for_editor(
        structure,
        mounted=mounted_admin_panels(deps),
    )
    structure_raw = admin_nav_structure_to_raw(structure)
    return _TEMPLATES.TemplateResponse(
        request,
        "nav_settings.html",
        page_context(
            request,
            deps,
            structure=structure,
            structure_json=json.dumps(structure_raw, ensure_ascii=False),
        ),
    )
