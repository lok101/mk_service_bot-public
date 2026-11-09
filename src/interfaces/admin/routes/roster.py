from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from src.application.master_data import run_master_data_sheets_export
from src.application.reference_data import (
    ApplyLocationRosterDraft,
    LocationRosterConflict,
    LocationRosterEntry,
    LocationRosterInvalid,
    LocationRosterPatch,
    ResetLocationRosterDraft,
    UpsertLocationRosterDraft,
)
from src.application.service_visits import (
    RefreshScheduledVisitsForRosterChange,
    RosterWeekdayChange,
)
from src.application.sheets import list_all_machines_from_snapshot
from src.domain.ids import MachineId, TechnicianId
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
from src.interfaces.admin.page_builders import (
    _active_store_technician_ids,
    build_roster_page_sync,
)

_LOGGER = logging.getLogger(__name__)
_ROSTER_PATH = "/admin/roster"
_ROSTER_CONFLICT_REDIRECT = f"{_ROSTER_PATH}?conflict=1"


@beartype
def register_roster_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    async def _roster_mutating_post(
        request: Request,
        handler: Callable[..., Response],
    ) -> Response:
        actor = _require_roster_actor(request, deps)
        if isinstance(actor, Response):
            return actor
        fields = await form_fields(request, deps)
        return handler(deps, actor_telegram_user_id=actor, fields=fields)

    @router.get("/roster")
    async def roster_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.ROSTER)
        if isinstance(actor, Response):
            return actor
        payload = await asyncio.to_thread(
            build_roster_page_sync,
            deps,
            actor_telegram_user_id=actor,
        )
        view = payload.view
        conflict = request.query_params.get("conflict") == "1"
        return _TEMPLATES.TemplateResponse(
            request,
            "roster.html",
            page_context(
                request,
                deps,
                rows=view.rows,
                technicians=view.technicians,
                map_coordinates_available=view.map_coordinates_available,
                draft_dirty=view.draft_dirty,
                roster_conflict=conflict,
            ),
        )

    @router.post("/roster")
    async def roster_post_legacy() -> Response:
        return Response(status_code=405)

    @router.post("/roster/draft")
    async def roster_draft_post(request: Request) -> Response:
        return await _roster_mutating_post(request, _upsert_roster_draft)

    @router.post("/roster/apply")
    async def roster_apply_post(request: Request) -> Response:
        return await _roster_mutating_post(request, _apply_roster_draft)

    @router.post("/roster/reset")
    async def roster_reset_post(request: Request) -> Response:
        return await _roster_mutating_post(request, _reset_roster_draft)


def _require_roster_actor(request: Request, deps: AdminHttpDeps) -> int | Response:
    actor = require_panel(request, deps, AdminPanel.ROSTER)
    if isinstance(actor, Response):
        return actor
    if not origin_allowed(request):
        _LOGGER.info("admin_roster_origin_reject")
        return Response(status_code=403)
    return actor


def _roster_catalog_ids(deps: AdminHttpDeps) -> frozenset[MachineId]:
    catalog = deps.provider.locations_catalog()
    return frozenset(machine.id for machine in list_all_machines_from_snapshot(catalog))


@beartype
def _export_mirror_after_roster(deps: AdminHttpDeps) -> None:
    if deps.master_stores is None:
        return
    run_master_data_sheets_export(deps.master_data_export_hook, deps.master_stores)


def _parse_optional_iso(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _expected_updated_at_map(
    fields: dict[str, str],
    *,
    prefix: str,
) -> dict[MachineId, datetime]:
    result: dict[MachineId, datetime] = {}
    for key, value in fields.items():
        if not key.startswith(prefix):
            continue
        machine_raw = key.removeprefix(prefix)
        if not machine_raw:
            continue
        parsed = _parse_optional_iso(value)
        if parsed is None:
            continue
        result[MachineId(machine_raw)] = parsed
    return result


def _assert_active_technician_assign(
    deps: AdminHttpDeps,
    *,
    technician_id: TechnicianId,
    previous: LocationRosterEntry | None,
) -> None:
    if previous is not None and previous.technician_id == technician_id:
        return
    active_technician_ids = {
        user.technician_id
        for user in deps.provider.system_users().users_by_telegram_id.values()
        if user.is_active and user.technician_id is not None
    }
    if technician_id not in active_technician_ids:
        raise LocationRosterInvalid(f"Inactive technician {technician_id.value!r}")
    active_store_ids = _active_store_technician_ids(deps)
    if active_store_ids is not None and technician_id not in active_store_ids:
        raise LocationRosterInvalid(f"Inactive technician {technician_id.value!r}")


def _refresh_visits_and_mirror(
    deps: AdminHttpDeps,
    *,
    before: dict[MachineId, LocationRosterEntry | None],
    entries: tuple[LocationRosterEntry, ...],
) -> None:
    _export_mirror_after_roster(deps)
    weekday_changes: list[RosterWeekdayChange] = []
    unassigned_machine_ids: list[MachineId] = []
    for entry in entries:
        previous = before.get(entry.machine_id)
        previous_days = frozenset() if previous is None else previous.service_weekdays
        if previous_days != entry.service_weekdays:
            weekday_changes.append(
                RosterWeekdayChange(
                    machine_id=entry.machine_id, service_weekdays=entry.service_weekdays
                )
            )
        previous_tech = None if previous is None else previous.technician_id
        if previous_tech is not None and entry.technician_id is None:
            unassigned_machine_ids.append(entry.machine_id)
    result = RefreshScheduledVisitsForRosterChange(
        store=deps.visit_store,
        maintenance_lookup=deps.maintenance_lookup,
        timezone=deps.timezone,
        day_end_hour=deps.day_end_hour,
    ).execute(
        changes=tuple(weekday_changes),
        unassigned_machine_ids=tuple(unassigned_machine_ids),
        now=deps.now_factory(),
        timezone=deps.timezone,
        day_end_hour=deps.day_end_hour,
    )
    _LOGGER.info(
        "roster_visits_refresh",
        extra={
            "upserted": result.upserted,
            "cancelled": result.cancelled,
            "retrospectively_closed": result.retrospectively_closed,
        },
    )


def _upsert_roster_draft(
    deps: AdminHttpDeps,
    *,
    actor_telegram_user_id: int,
    fields: dict[str, str],
) -> Response:
    machine_raw = fields.get("machine_id", "").strip()
    if not machine_raw:
        return Response(status_code=400)
    machine_id = MachineId(machine_raw)
    tech_raw = fields.get(f"technician-{machine_raw}", "").strip()
    weekdays = frozenset(iso for iso in range(7) if fields.get(f"wd-{machine_raw}-{iso}"))
    patch = LocationRosterPatch(
        machine_id=machine_id,
        technician_id=TechnicianId(tech_raw) if tech_raw else None,
        service_weekdays=weekdays,
    )
    catalog_ids = _roster_catalog_ids(deps)
    try:
        if patch.technician_id is not None:
            previous = deps.roster_draft_store.get(machine_id)
            if previous is None:
                previous = deps.roster_store.get(machine_id)
            _assert_active_technician_assign(
                deps,
                technician_id=patch.technician_id,
                previous=previous,
            )
        entry = UpsertLocationRosterDraft(draft=deps.roster_draft_store).execute(
            patch,
            expected_updated_at=_parse_optional_iso(fields.get("expected_updated_at")),
            catalog_machine_ids=catalog_ids,
            directory_technician_ids=frozenset(
                deps.provider.technicians_directory().names_by_id.keys()
            ),
            actor_telegram_user_id=actor_telegram_user_id,
            now=deps.now_factory(),
        )
    except LocationRosterInvalid:
        return Response(status_code=400)
    except LocationRosterConflict:
        _LOGGER.info(
            "location_roster_conflict",
            extra={"actor": actor_telegram_user_id, "machine_id": machine_raw},
        )
        return Response(status_code=409)
    _LOGGER.info(
        "location_roster_draft_write",
        extra={"actor": actor_telegram_user_id, "machine_id": machine_raw},
    )
    return JSONResponse({"ok": True, "updated_at": entry.updated_at.isoformat()})


def _apply_roster_draft(
    deps: AdminHttpDeps,
    *,
    actor_telegram_user_id: int,
    fields: dict[str, str],
) -> Response:
    catalog_ids = _roster_catalog_ids(deps)
    directory = deps.provider.technicians_directory()
    before = {machine_id: deps.roster_store.get(machine_id) for machine_id in catalog_ids}
    expected_draft = _expected_updated_at_map(fields, prefix="expected_draft_updated_at-")
    expected_applied = _expected_updated_at_map(fields, prefix="expected_applied_updated_at-")
    try:
        for machine_id in catalog_ids:
            draft_entry = deps.roster_draft_store.get(machine_id)
            if draft_entry is None or draft_entry.technician_id is None:
                continue
            _assert_active_technician_assign(
                deps,
                technician_id=draft_entry.technician_id,
                previous=before.get(machine_id),
            )
        result = ApplyLocationRosterDraft(
            draft=deps.roster_draft_store,
            applied=deps.roster_store,
            on_applied=lambda entries: _refresh_visits_and_mirror(
                deps,
                before=before,
                entries=entries,
            ),
        ).execute(
            catalog_machine_ids=catalog_ids,
            directory_technician_ids=frozenset(directory.names_by_id.keys()),
            expected_draft_updated_at=expected_draft,
            expected_applied_updated_at=expected_applied,
            actor_telegram_user_id=actor_telegram_user_id,
            now=deps.now_factory(),
        )
    except LocationRosterInvalid:
        return Response(status_code=400)
    except LocationRosterConflict:
        _LOGGER.info(
            "location_roster_conflict",
            extra={"actor": actor_telegram_user_id, "n": len(catalog_ids)},
        )
        return RedirectResponse(_ROSTER_CONFLICT_REDIRECT, status_code=303)
    _LOGGER.info(
        "location_roster_apply",
        extra={"actor": actor_telegram_user_id, "n": len(catalog_ids), "applied": result.applied},
    )
    return RedirectResponse(_ROSTER_PATH, status_code=303)


def _reset_roster_draft(
    deps: AdminHttpDeps,
    *,
    actor_telegram_user_id: int,
    fields: dict[str, str],
) -> Response:
    catalog_ids = _roster_catalog_ids(deps)
    expected_draft = _expected_updated_at_map(fields, prefix="expected_draft_updated_at-")
    try:
        ResetLocationRosterDraft(
            draft=deps.roster_draft_store,
            applied=deps.roster_store,
        ).execute(
            catalog_machine_ids=catalog_ids,
            expected_draft_updated_at=expected_draft,
            now=deps.now_factory(),
            actor_telegram_user_id=actor_telegram_user_id,
        )
    except LocationRosterConflict:
        _LOGGER.info(
            "location_roster_conflict",
            extra={"actor": actor_telegram_user_id, "n": len(catalog_ids)},
        )
        return RedirectResponse(_ROSTER_CONFLICT_REDIRECT, status_code=303)
    _LOGGER.info(
        "location_roster_draft_reset",
        extra={"actor": actor_telegram_user_id, "n": len(catalog_ids)},
    )
    return RedirectResponse(_ROSTER_PATH, status_code=303)
