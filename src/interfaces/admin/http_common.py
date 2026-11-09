from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from beartype import beartype
from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from src.domain.system_user import AdminPanel, BotRole
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.session import (
    admin_session_cookie_name,
    pack_admin_session,
    unpack_admin_session,
)
from src.interfaces.admin.system_users_view import build_nav_items, build_nav_tree_for_request
from src.interfaces.http.bounded_body import read_bounded_request_body

_LOGGER = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


@beartype
def static_version(name: str) -> str:
    path = _STATIC_DIR / name
    return str(int(path.stat().st_mtime)) if path.is_file() else "0"


@beartype
def static_href(name: str) -> str:
    return f"/admin/static/{name}?v={static_version(name)}"


_TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES = Jinja2Templates(directory=str(_TEMPLATES_DIR))
TEMPLATES.env.globals["static_href"] = static_href


@beartype
def planogram_static_context() -> dict[str, str]:
    return {
        "planogram_js_href": static_href("planogram.js"),
        "planogram_css_href": static_href("planogram.css"),
        "admin_quantity_stepper_js_href": static_href("admin_quantity_stepper.js"),
        "planogram_product_picker_js_href": static_href("planogram_product_picker.js"),
        "micromarket_planogram_sort_key_js_href": static_href("micromarket_planogram_sort_key.js"),
        "micromarket_planogram_table_js_href": static_href("micromarket_planogram_table.js"),
        "micromarket_planogram_publish_js_href": static_href("micromarket_planogram_publish.js"),
    }


LOGIN_PATH = "/admin/login"


def _user_may_access_admin(
    deps: AdminHttpDeps,
    telegram_user_id: int,
    panel: AdminPanel,
) -> bool:
    snapshot = deps.provider.system_users_or_none()
    if snapshot is None:
        return False
    user = snapshot.users_by_telegram_id.get(telegram_user_id)
    if user is None or not user.is_active:
        return False
    if not deps.users_enabled:
        return user.role is BotRole.ADMINISTRATOR
    return panel in user.panels


@beartype
def user_has_panel(deps: AdminHttpDeps, telegram_user_id: int, panel: AdminPanel) -> bool:
    return _user_may_access_admin(deps, telegram_user_id, panel)


@beartype
def require_panel(request: Request, deps: AdminHttpDeps, panel: AdminPanel) -> int | Response:
    user_id = session_user_id(request, deps)
    if user_id is None:
        return RedirectResponse(LOGIN_PATH, status_code=303)
    if not _user_may_access_admin(deps, user_id, panel):
        _LOGGER.info(
            "admin_panel_forbidden",
            extra={"telegram_user_id": user_id, "panel": panel.value},
        )
        return Response(status_code=403)
    return user_id


@beartype
def require_any_panel(
    request: Request,
    deps: AdminHttpDeps,
    panels: tuple[AdminPanel, ...] | list[AdminPanel] | frozenset[AdminPanel],
) -> int | Response:
    user_id = session_user_id(request, deps)
    if user_id is None:
        return RedirectResponse(LOGIN_PATH, status_code=303)
    allowed = tuple(panels)
    if not any(_user_may_access_admin(deps, user_id, panel) for panel in allowed):
        _LOGGER.info(
            "admin_panel_forbidden",
            extra={
                "telegram_user_id": user_id,
                "panel": ",".join(panel.value for panel in allowed),
            },
        )
        return Response(status_code=403)
    return user_id


@beartype
def origin_allowed(request: Request) -> bool:
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if origin:
        return urlparse(origin).netloc == host
    referer = request.headers.get("referer")
    if not referer:
        return False
    return urlparse(referer).netloc == host


@beartype
async def read_admin_body(request: Request, deps: AdminHttpDeps) -> bytes:
    return await read_bounded_request_body(
        request,
        max_body_bytes=deps.admin_max_body_bytes,
    )


@beartype
async def form_fields(request: Request, deps: AdminHttpDeps) -> dict[str, str]:
    body = (await read_admin_body(request, deps)).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


@beartype
def page_context(
    request: Request,
    deps: AdminHttpDeps,
    **extra: object,
) -> dict[str, object]:
    return {
        "nav_tree": build_nav_tree_for_request(
            deps,
            telegram_user_id=session_user_id(request, deps),
            request_path=str(request.url.path),
        ),
        "technicians_enabled": deps.technicians_enabled,
        "master_profile_links": deps.master_stores is not None,
        "admin_css_href": static_href("admin.css"),
        **extra,
    }


@beartype
def complete_login(request: Request, deps: AdminHttpDeps, user_id: int) -> Response:
    snapshot = deps.provider.system_users_or_none()
    user = None if snapshot is None else snapshot.users_by_telegram_id.get(user_id)
    if user is None:
        _LOGGER.info(
            "admin_login_fail",
            extra={"reason": "unknown_user", "telegram_user_id": user_id},
        )
        return Response(status_code=403)
    if not user.is_active:
        _LOGGER.info(
            "admin_login_fail",
            extra={"reason": "inactive", "telegram_user_id": user_id},
        )
        return Response(status_code=403)
    if not deps.users_enabled:
        if user.role is not BotRole.ADMINISTRATOR:
            _LOGGER.info(
                "admin_login_fail",
                extra={"reason": "role", "telegram_user_id": user_id},
            )
            return Response(status_code=403)
    elif not user.panels:
        _LOGGER.info(
            "admin_login_fail",
            extra={"reason": "no_panels", "telegram_user_id": user_id},
        )
        return Response(status_code=403)
    _LOGGER.info("admin_login_ok", extra={"telegram_user_id": user_id})
    nav = build_nav_items(deps, telegram_user_id=user_id)
    if not nav:
        return Response(status_code=403)
    landing = nav[0].href
    response = RedirectResponse(landing, status_code=303)
    issued_at = int(deps.now_factory().timestamp())
    token = pack_admin_session(
        telegram_user_id=user_id,
        issued_at=issued_at,
        secret=deps.session_secret,
    )
    response.set_cookie(
        key=admin_session_cookie_name(),
        value=token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=deps.session_ttl_seconds,
        path="/admin",
    )
    return response


@beartype
def session_user_id(request: Request, deps: AdminHttpDeps) -> int | None:
    token = request.cookies.get(admin_session_cookie_name())
    if not token:
        return None
    return unpack_admin_session(
        token,
        secret=deps.session_secret,
        ttl_seconds=deps.session_ttl_seconds,
        now_epoch=int(deps.now_factory().timestamp()),
    )
