from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.sales_monitoring import (
    OFFLINE_CHECK_ABSENT,
    engineer_wait_document_id,
    history_window,
    live_group,
    live_row_note,
    mute_cancel_document_id,
    mute_document_id,
    no_sales_episode_clear_kind,
    open_no_sales_session_id,
    select_no_sales_history_documents,
    task_suppressed_reason,
)
from src.domain.ids import MachineId
from src.domain.sales_monitoring.control_event import NoSalesIncidentControlAction
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    origin_allowed,
    page_context,
    require_panel,
)
from src.interfaces.admin.incident_history_view import (
    incident_history_choices,
    present_incident_history_row,
)
from src.interfaces.admin.incident_live_view import (
    incident_machine_screen_name,
    live_incident_choices,
)

_LIVE_PATH = "/admin/machine-incidents"
_HISTORY_PATH = "/admin/machine-incidents/history"

__all__ = ["register_machine_incidents_routes"]


@beartype
@dataclass(frozen=True, slots=True)
class _LiveRow:
    machine_id: str
    title: str
    group: str
    name: str
    note: str
    reason: str
    opened_event_id: str


@beartype
@dataclass(frozen=True, slots=True)
class _HistoryRow:
    machine_id: str
    opened_at: datetime | None
    cleared_at: datetime | None
    technician: str
    reason: str | None
    clear_kind: str


@beartype
def register_machine_incidents_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    if deps.master_stores is None or deps.build_visit_board is None:
        return

    @router.get("/machine-incidents")
    async def machine_incidents_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_BOARD)
        if isinstance(actor, Response):
            return actor
        rows = await asyncio.to_thread(_build_live_rows, deps)
        return _TEMPLATES.TemplateResponse(
            request,
            "machine_incidents.html",
            page_context(
                request,
                deps,
                main_class="admin-main--full-width",
                engineer_rows=[row for row in rows if row.group == "engineer"],
                problem_rows=[row for row in rows if row.group == "problem"],
                muted_rows=[row for row in rows if row.group == "muted"],
                note_choices=live_incident_choices([row.note for row in rows]),
                reason_choices=live_incident_choices([row.reason for row in rows]),
                row_count=len(rows),
                offline_check_absent=OFFLINE_CHECK_ABSENT,
            ),
        )

    @router.get("/machine-incidents/history")
    async def machine_incidents_history_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_BOARD)
        if isinstance(actor, Response):
            return actor
        raw_from = request.query_params.get("from")
        raw_to = request.query_params.get("to")
        try:
            start, end = history_window(
                now=deps.now_factory(),
                raw_from=raw_from,
                raw_to=raw_to,
            )
        except ValueError:
            return RedirectResponse(_HISTORY_PATH, status_code=303)
        rows = await asyncio.to_thread(_build_history_rows, deps, start=start, end=end)
        view_rows = [
            present_incident_history_row(
                machine_id=row.machine_id,
                name=incident_machine_screen_name(deps.master_stores, row.machine_id),
                opened_at=row.opened_at,
                cleared_at=row.cleared_at,
                technician=row.technician,
                reason=row.reason,
                clear_kind=row.clear_kind,
                timezone=deps.timezone,
            )
            for row in rows
        ]
        return _TEMPLATES.TemplateResponse(
            request,
            "machine_incidents_history.html",
            page_context(
                request,
                deps,
                rows=view_rows,
                technician_choices=incident_history_choices([row.technician for row in view_rows]),
                reason_choices=incident_history_choices([row.reason for row in view_rows]),
                clear_kind_choices=incident_history_choices([row.clear_kind for row in view_rows]),
                raw_from=start.date().isoformat(),
                raw_to=end.date().isoformat(),
            ),
        )

    @router.post("/machine-incidents/{machine_id}/mute")
    async def machine_incidents_mute_post(request: Request, machine_id: str) -> Response:
        return await _control_post(request, deps, machine_id=machine_id, action="mute")

    @router.post("/machine-incidents/{machine_id}/mute-cancel")
    async def machine_incidents_mute_cancel_post(request: Request, machine_id: str) -> Response:
        return await _control_post(request, deps, machine_id=machine_id, action="mute_cancel")

    @router.post("/machine-incidents/{machine_id}/engineer-wait")
    async def machine_incidents_engineer_wait_post(request: Request, machine_id: str) -> Response:
        return await _control_post(request, deps, machine_id=machine_id, action="engineer_wait")


@beartype
async def _control_post(
    request: Request,
    deps: AdminHttpDeps,
    *,
    machine_id: str,
    action: NoSalesIncidentControlAction,
) -> Response:
    actor = require_panel(request, deps, AdminPanel.VISIT_BOARD)
    if isinstance(actor, Response):
        return actor
    if not origin_allowed(request):
        return Response(status_code=403)
    if deps.enqueue_no_sales_incident_control is None or deps.list_open_no_sales is None:
        return Response(status_code=503)
    opened = await asyncio.to_thread(_find_open_document, deps, machine_id)
    if opened is None:
        return Response(status_code=404)
    opened_event_id = open_no_sales_session_id(opened)
    if opened_event_id is None:
        return Response(status_code=404)
    mid = MachineId(machine_id)
    if action == "mute_cancel" and not await asyncio.to_thread(
        _has_mute_document,
        deps,
        mid,
        opened_event_id,
    ):
        return Response(status_code=404)
    await asyncio.to_thread(
        deps.enqueue_no_sales_incident_control,
        machine_id=mid,
        opened_event_id=opened_event_id,
        action=action,
    )
    return RedirectResponse(_LIVE_PATH, status_code=303)


@beartype
def _find_open_document(deps: AdminHttpDeps, machine_id: str) -> dict[str, object] | None:
    if deps.list_open_no_sales is None:
        return None
    for document in deps.list_open_no_sales():
        if document.get("machine_id") == machine_id:
            return document
    return None


@beartype
def _has_mute_document(
    deps: AdminHttpDeps,
    machine_id: MachineId,
    opened_event_id: str,
) -> bool:
    if deps.list_no_sales_controls is None:
        return False
    mute_id = mute_document_id(machine_id, opened_event_id)
    return any(
        document.get("_id") == mute_id for document in deps.list_no_sales_controls(machine_id)
    )


@beartype
def _build_live_rows(deps: AdminHttpDeps) -> list[_LiveRow]:
    if deps.list_open_no_sales is None:
        return []
    offline_ids = {
        str(document.get("machine_id"))
        for document in (deps.list_open_offline() if deps.list_open_offline is not None else [])
    }
    rows: list[_LiveRow] = []
    for document in deps.list_open_no_sales():
        machine_id_raw = document.get("machine_id")
        opened_event_id_raw = open_no_sales_session_id(document)
        if not isinstance(machine_id_raw, str) or opened_event_id_raw is None:
            continue
        machine_id = MachineId(machine_id_raw)
        engineer, muted = _control_flags(deps, machine_id, opened_event_id_raw)
        kind = _machine_kind(deps, machine_id)
        visit_allowed = _visit_allowed(deps, machine_id)
        note = live_row_note(kind=kind, vending_offline=machine_id_raw in offline_ids)
        reason = task_suppressed_reason(
            engineer=engineer,
            muted=muted,
            visit_allowed=visit_allowed,
            turnover_suppressed=False,
        )
        group = live_group(engineer=engineer, muted=muted)
        rows.append(
            _LiveRow(
                machine_id=machine_id_raw,
                title=_machine_title(deps, machine_id_raw),
                name=incident_machine_screen_name(deps.master_stores, machine_id_raw),
                group=group,
                note=note or "—",
                reason=reason or ("задача есть" if group == "problem" else "—"),
                opened_event_id=opened_event_id_raw,
            )
        )
    return rows


@beartype
def _build_history_rows(
    deps: AdminHttpDeps,
    *,
    start: datetime,
    end: datetime,
) -> list[_HistoryRow]:
    episodes: list[dict[str, object]] = []
    if deps.list_no_sales_episodes_overlapping is not None:
        episodes = list(deps.list_no_sales_episodes_overlapping(start=start, end=end))
    open_documents: list[dict[str, object]] = []
    if deps.list_open_no_sales is not None:
        open_documents = list(deps.list_open_no_sales())
    cleared_documents: list[dict[str, object]] = []
    if deps.list_cleared_no_sales_since is not None:
        cleared_documents = list(deps.list_cleared_no_sales_since(cleared_at_gte=start))
    documents = select_no_sales_history_documents(
        episodes=episodes,
        open_documents=open_documents,
        cleared_documents=cleared_documents,
        start=start,
        end=end,
    )
    pair_minutes = (
        deps.incident_clear_pair_minutes if deps.incident_clear_pair_minutes is not None else 30
    )
    now = deps.now_factory()
    rows: list[_HistoryRow] = []
    for document in documents:
        machine_id_raw = document.get("machine_id")
        if not isinstance(machine_id_raw, str):
            continue
        opened_at = document.get("opened_at")
        cleared_at = document.get("cleared_at")
        opened_event_id = open_no_sales_session_id(document)
        engineer = False
        muted = False
        if opened_event_id is not None:
            engineer, muted = _control_flags(deps, MachineId(machine_id_raw), opened_event_id)
        visit_allowed = _visit_allowed(deps, MachineId(machine_id_raw))
        reason = task_suppressed_reason(
            engineer=engineer,
            muted=muted,
            visit_allowed=visit_allowed,
            turnover_suppressed=False,
        )
        tech = document.get("assigned_technician_display")
        clear_kind = _history_clear_kind(
            deps,
            document=document,
            machine_id=machine_id_raw,
            now=now,
            pair_minutes=pair_minutes,
        )
        rows.append(
            _HistoryRow(
                machine_id=machine_id_raw,
                opened_at=opened_at if isinstance(opened_at, datetime) else None,
                cleared_at=cleared_at if isinstance(cleared_at, datetime) else None,
                technician=str(tech) if isinstance(tech, str) and tech else "—",
                reason=reason,
                clear_kind=clear_kind,
            )
        )
    return rows


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _history_clear_kind(
    deps: AdminHttpDeps,
    *,
    document: dict[str, object],
    machine_id: str,
    now: datetime,
    pair_minutes: int,
) -> str:
    if document.get("kind") == "no_sales_episode":
        trigger_raw = document.get("clear_trigger")
        clear_trigger: Literal["sale", "exclude"] | None
        if trigger_raw in ("sale", "exclude"):  # noqa: SIM108
            clear_trigger = trigger_raw
        else:
            clear_trigger = None
        last_sale_at = document.get("last_sale_at")
        sale_at = last_sale_at if isinstance(last_sale_at, datetime) else None
        cleared_at_raw = document.get("cleared_at")
        cleared_at = cleared_at_raw if isinstance(cleared_at_raw, datetime) else None
        bypass_raw = document.get("bypass_active")
        bypass_active = bypass_raw if isinstance(bypass_raw, bool) else None
        completions = _maintenance_completions_near_sale(
            deps,
            machine_id=machine_id,
            last_sale_at=sale_at,
            pair_minutes=pair_minutes,
        )
        return no_sales_episode_clear_kind(
            cleared_at=cleared_at,
            clear_trigger=clear_trigger,
            bypass_active=bypass_active,
            last_sale_at=sale_at,
            maintenance_completed_ats=completions,
            now=now,
            pair_minutes=pair_minutes,
        )
    if document.get("status") == "cleared":
        return "cleared"
    return ""


@beartype
def _maintenance_completions_near_sale(
    deps: AdminHttpDeps,
    *,
    machine_id: str,
    last_sale_at: datetime | None,
    pair_minutes: int,
) -> tuple[datetime, ...]:
    lookup = deps.list_maintenance_completed_in_completed_at_window
    if lookup is None or last_sale_at is None:
        return ()
    sale = _as_utc(last_sale_at)
    window = timedelta(minutes=pair_minutes)
    events = lookup(
        MachineId(machine_id),
        completed_at_start_inclusive=sale - window,
        completed_at_end_exclusive=sale + window + timedelta(microseconds=1),
    )
    completions: list[datetime] = []
    for event in events:
        completed_at = getattr(event, "completed_at", None)
        if isinstance(completed_at, datetime):
            completions.append(completed_at)
    return tuple(completions)


@beartype
def _control_flags(
    deps: AdminHttpDeps,
    machine_id: MachineId,
    opened_event_id: str,
) -> tuple[bool, bool]:
    if deps.list_no_sales_controls is None:
        return False, False
    ids = {document.get("_id") for document in deps.list_no_sales_controls(machine_id)}
    mute_id = mute_document_id(machine_id, opened_event_id)
    engineer = engineer_wait_document_id(machine_id, opened_event_id) in ids
    muted = mute_id in ids and mute_cancel_document_id(machine_id, mute_id) not in ids
    return engineer, muted


@beartype
def _machine_kind(deps: AdminHttpDeps, machine_id: MachineId) -> str:
    stores = deps.master_stores
    if stores is None:
        return "coffee"
    machine = stores.machines.get(machine_id)
    if machine is None:
        return "coffee"
    return machine.kind.value


@beartype
def _visit_allowed(deps: AdminHttpDeps, machine_id: MachineId) -> bool:
    stores = deps.master_stores
    if stores is None:
        return True
    machine = stores.machines.get(machine_id)
    if machine is None:
        return True
    return machine.create_visit_on_no_sales


@beartype
def _machine_title(deps: AdminHttpDeps, machine_id: str) -> str:
    stores = deps.master_stores
    if stores is None:
        return machine_id
    machine = stores.machines.get(MachineId(machine_id))
    if machine is None:
        return machine_id
    return machine_id
