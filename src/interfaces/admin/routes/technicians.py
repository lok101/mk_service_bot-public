from __future__ import annotations

import asyncio
import logging

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import (
    FieldStaffInvalid,
    FieldStaffRowDraft,
    TechnicianValidationError,
    hydrate_technicians_directory,
)
from src.domain.ids import TechnicianId
from src.domain.system_user import AdminPanel, BotRole, SystemUserId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.field_staff_view import build_field_staff_page_view
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    page_context,
    require_panel,
)
from src.interfaces.admin.routes.users import _refresh_provider_system_users
from src.interfaces.admin.technicians_view import (
    build_technician_edit_view,
    parse_technician_list_status,
)

_LOGGER = logging.getLogger(__name__)
_TECHNICIANS_PATH = "/admin/technicians"

__all__ = [
    "_refresh_provider_technicians",
    "register_technicians_routes",
]


@beartype
def register_technicians_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    store = deps.system_user_store
    save_field_staff = deps.save_field_staff
    assert save_field_staff is not None

    @router.get("/technicians")
    async def technicians_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.TECHNICIANS)
        if isinstance(actor, Response):
            return actor
        return _technicians_page(request, deps)

    @router.post("/technicians")
    async def technicians_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.TECHNICIANS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_technicians_origin_reject")
            return Response(status_code=403)
        actor_panels = frozenset[AdminPanel]()
        if store is not None:
            actor_record = store.get(actor)
            if actor_record is not None:
                actor_panels = actor_record.user.panels
        fields = await form_fields(request, deps)
        try:
            rows = _field_staff_rows_from_form(fields)

            def _save() -> None:
                save_field_staff.execute(
                    rows,
                    actor_telegram_user_id=actor,
                    actor_panels=actor_panels,
                    now=deps.now_factory(),
                )

            await asyncio.to_thread(_save)
        except (FieldStaffInvalid, ValueError) as exc:
            _LOGGER.info("admin_technicians_save_reject", extra={"reason": str(exc)})
            return _technicians_page(request, deps, error=str(exc), status_code=400)
        try:
            await asyncio.to_thread(_refresh_provider_system_users, deps)
            await asyncio.to_thread(_refresh_provider_technicians, deps)
        except Exception:
            _LOGGER.exception("admin_technicians_hydrate_failed")
            return Response(status_code=500)
        _LOGGER.info("admin_field_staff_save", extra={"actor": actor, "n": len(rows)})
        return RedirectResponse(_TECHNICIANS_PATH, status_code=303)

    @router.get("/technicians/{technician_id}")
    async def technician_edit_get(request: Request, technician_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.TECHNICIANS)
        if isinstance(actor, Response):
            return actor
        return _technician_edit_page(request, deps, technician_id)

    @router.post("/technicians/{technician_id}")
    async def technician_edit_post(request: Request, technician_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.TECHNICIANS)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            _LOGGER.info("admin_technicians_origin_reject")
            return Response(status_code=403)
        update = deps.update_technician
        tech_store = deps.technician_store
        if update is None or tech_store is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        name = fields.get("name", "")
        is_active = "is_active" in fields
        try:

            def _update() -> None:
                update.execute(
                    technician_id=TechnicianId(technician_id),
                    name=name,
                    is_active=is_active,
                    actor_telegram_user_id=actor,
                    now=deps.now_factory(),
                )

            await asyncio.to_thread(_update)
        except TechnicianValidationError as exc:
            _LOGGER.info("admin_technicians_update_reject", extra={"reason": str(exc)})
            existing = tech_store.get(TechnicianId(technician_id))
            if existing is None:
                return Response(status_code=404)
            return _technician_edit_page(
                request,
                deps,
                technician_id,
                error=str(exc),
                status_code=400,
            )
        try:
            await asyncio.to_thread(_refresh_provider_technicians, deps)
        except Exception:
            _LOGGER.exception("admin_technicians_hydrate_failed")
            return Response(status_code=500)
        _LOGGER.info(
            "admin_technicians_update",
            extra={"actor": actor, "technician_id": technician_id},
        )
        return RedirectResponse(_TECHNICIANS_PATH, status_code=303)


def _technicians_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    tech_store = deps.technician_store
    user_store = deps.system_user_store
    if tech_store is None or user_store is None:
        return Response(status_code=404)
    status = parse_technician_list_status(request.query_params.get("status"))
    view = build_field_staff_page_view(tech_store, user_store, status=status)
    return _TEMPLATES.TemplateResponse(
        request,
        "technicians.html",
        page_context(
            request,
            deps,
            rows=view.rows,
            status=view.status,
            bot_roles=view.bot_roles,
            error=error,
        ),
        status_code=status_code,
    )


def _technician_edit_page(
    request: Request,
    deps: AdminHttpDeps,
    technician_id: str,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    store = deps.technician_store
    if store is None:
        return Response(status_code=404)
    existing = store.get(TechnicianId(technician_id))
    if existing is None:
        return Response(status_code=404)
    view = build_technician_edit_view(existing)
    return _TEMPLATES.TemplateResponse(
        request,
        "technician_edit.html",
        page_context(
            request,
            deps,
            technician=view,
            error=error,
        ),
        status_code=status_code,
    )


def _refresh_provider_technicians(deps: AdminHttpDeps) -> None:
    store = deps.technician_store
    if store is None:
        return
    hydrate_technicians_directory(deps.provider, store)


def _field_staff_rows_from_form(fields: dict[str, str]) -> tuple[FieldStaffRowDraft, ...]:
    indices = _field_staff_row_indices(fields)
    if not indices:
        raise FieldStaffInvalid("no field staff rows in form")
    rows = tuple(
        row
        for index in indices
        if (row := _field_staff_row_from_indexed_row(fields, index)) is not None
    )
    if not rows:
        raise FieldStaffInvalid("no field staff rows in form")
    return rows


def _field_staff_row_from_indexed_row(
    fields: dict[str, str],
    index: int,
) -> FieldStaffRowDraft | None:
    name = fields.get(f"name-{index}", "").strip()
    telegram_raw = fields.get(f"telegram_user_id-{index}", "").strip()
    technician_raw = fields.get(f"technician_id-{index}", "").strip()
    if not name and not telegram_raw:
        return None
    if technician_raw and not telegram_raw:
        return None
    if not name or not telegram_raw:
        raise FieldStaffInvalid(f"incomplete field staff row {index}")
    return FieldStaffRowDraft(
        telegram_user_id=int(telegram_raw),
        name=name,
        bot_role=BotRole(fields.get(f"bot_role-{index}", BotRole.TECHNICIAN.value).strip()),
        is_active=bool(fields.get(f"is_active-{index}")),
        user_id=_optional_user_id(fields.get(f"user_id-{index}", "")),
        technician_is_active=bool(fields.get(f"technician_is_active-{index}")),
        linked_technician_id=_optional_technician_id(technician_raw),
    )


def _field_staff_row_indices(fields: dict[str, str]) -> tuple[int, ...]:
    found: set[int] = set()
    for key in fields:
        if key.startswith("name-"):
            suffix = key.removeprefix("name-")
            if suffix.isdigit():
                found.add(int(suffix))
                continue
        if key.startswith("telegram_user_id-"):
            suffix = key.removeprefix("telegram_user_id-")
            if suffix.isdigit():
                found.add(int(suffix))
    return tuple(sorted(found))


def _optional_user_id(raw: str) -> SystemUserId | None:
    text = raw.strip()
    if not text:
        return None
    return SystemUserId(text)


def _optional_technician_id(raw: str) -> TechnicianId | None:
    text = raw.strip()
    if not text:
        return None
    return TechnicianId(text)
