from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import (
    SystemUserDraft,
    SystemUsersInvalid,
    hydrate_provider_from_system_users,
    technician_ids_for_system_users_validation,
)
from src.domain.system_user import AdminPanel, BotRole, CompanyRole, SystemUserId
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
from src.interfaces.admin.system_users_view import build_system_users_page_view

_LOGGER = logging.getLogger(__name__)
_USERS_PATH = "/admin/users"
_COMPANY_ROLE_FORM_KEYS: tuple[tuple[CompanyRole, str], ...] = tuple(
    (role, f"company_role_{role.value}") for role in CompanyRole
)

__all__ = [
    "_COMPANY_ROLE_FORM_KEYS",
    "_access_rows_from_users_form",
    "_refresh_provider_system_users",
    "register_system_users_routes",
]


@beartype
def register_system_users_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    store = deps.system_user_store
    assert store is not None
    assert deps.save_system_users is not None

    @router.get("/users")
    async def users_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.USERS)
        if isinstance(actor, Response):
            return actor
        return _users_page(request, deps)

    @router.post("/users")
    async def users_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.USERS)
        if isinstance(actor, Response):
            return actor
        actor_record = store.get(actor)
        if actor_record is None:
            return Response(status_code=403)
        actor_panels = actor_record.user.panels
        if not origin_allowed(request):
            _LOGGER.info("admin_users_origin_reject")
            return Response(status_code=403)
        save_system_users = deps.save_system_users
        if save_system_users is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        try:
            rows = _access_rows_from_users_form(fields)
            directory = deps.provider.technicians_directory()
            directory_ids = technician_ids_for_system_users_validation(
                technicians_enabled=deps.technicians_enabled,
                technician_store=deps.technician_store,
                directory_snapshot_ids=frozenset(directory.names_by_id.keys()),
            )

            def _save() -> None:
                save_system_users.execute(
                    tuple(_to_system_user_draft(row) for row in rows),
                    directory_technician_ids=directory_ids,
                    actor_telegram_user_id=actor,
                    actor_panels=actor_panels,
                    now=deps.now_factory(),
                    preserve_technician_links=True,
                )

            await asyncio.to_thread(_save)
        except (SystemUsersInvalid, ValueError) as exc:
            _LOGGER.info("admin_users_save_reject", extra={"reason": str(exc)})
            return _users_page(request, deps, error=str(exc), status_code=400)
        await asyncio.to_thread(_refresh_provider_system_users, deps)
        _LOGGER.info("system_users_save", extra={"actor": actor, "n": len(rows)})
        return RedirectResponse(_USERS_PATH, status_code=303)


def _users_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    store = deps.system_user_store
    assert store is not None
    view = build_system_users_page_view(store)
    return _TEMPLATES.TemplateResponse(
        request,
        "users.html",
        page_context(
            request,
            deps,
            rows=view.rows,
            bot_roles=view.bot_roles,
            all_company_roles=view.all_company_roles,
            company_role_labels=view.company_role_labels,
            error=error,
        ),
        status_code=status_code,
    )


def _refresh_provider_system_users(deps: AdminHttpDeps) -> None:
    store = deps.system_user_store
    if store is None:
        return
    hydrate_provider_from_system_users(deps.provider, store)


def _access_rows_from_users_form(fields: dict[str, str]) -> tuple[AccessRowDraft, ...]:
    indices = _user_row_indices(fields)
    if not indices:
        raise SystemUsersInvalid("no users in form")
    rows = tuple(
        row for index in indices if (row := _access_row_from_indexed_row(fields, index)) is not None
    )
    if not rows:
        raise SystemUsersInvalid("no users in form")
    return rows


def _access_row_from_indexed_row(fields: dict[str, str], index: int) -> AccessRowDraft | None:
    telegram_raw = fields.get(f"telegram_user_id-{index}", "").strip()
    name = fields.get(f"name-{index}", "").strip()
    if not telegram_raw and not name:
        return None
    if not telegram_raw or not name:
        raise SystemUsersInvalid(f"incomplete user row {index}")
    return AccessRowDraft(
        telegram_user_id=int(telegram_raw),
        name=name,
        bot_role=BotRole(fields.get(f"bot_role-{index}", BotRole.NONE.value).strip()),
        is_active=bool(fields.get(f"is_active-{index}")),
        company_roles=_company_roles_from_form(fields, index=index),
        user_id=_optional_user_id(fields.get(f"user_id-{index}", "")),
    )


@beartype
def _to_system_user_draft(row: AccessRowDraft) -> SystemUserDraft:
    return SystemUserDraft(
        telegram_user_id=row.telegram_user_id,
        name=row.name,
        bot_role=row.bot_role,
        is_active=row.is_active,
        technician_id=None,
        company_roles=row.company_roles,
        user_id=row.user_id,
    )


@beartype
@dataclass(frozen=True, slots=True)
class AccessRowDraft:
    telegram_user_id: int
    name: str
    bot_role: BotRole
    is_active: bool
    company_roles: frozenset[CompanyRole]
    user_id: SystemUserId | None


def _user_row_indices(fields: dict[str, str]) -> tuple[int, ...]:
    found: set[int] = set()
    for key in fields:
        if key.startswith("telegram_user_id-"):
            suffix = key.removeprefix("telegram_user_id-")
            if suffix.isdigit():
                found.add(int(suffix))
                continue
        if key.startswith("name-"):
            suffix = key.removeprefix("name-")
            if suffix.isdigit():
                found.add(int(suffix))
    return tuple(sorted(found))


def _company_roles_from_form(fields: dict[str, str], *, index: int) -> frozenset[CompanyRole]:
    roles: set[CompanyRole] = set()
    for role, key in _COMPANY_ROLE_FORM_KEYS:
        if fields.get(f"{key}-{index}"):
            roles.add(role)
    return frozenset(roles)


def _optional_user_id(raw: str) -> SystemUserId | None:
    text = raw.strip()
    if not text:
        return None
    return SystemUserId(text)
