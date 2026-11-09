from __future__ import annotations

import logging

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.domain.telegram_login_widget import TelegramLoginWidgetError, verify_telegram_login
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    LOGIN_PATH,
    complete_login,
    form_fields,
    page_context,
)
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.session import admin_session_cookie_name

_LOGGER = logging.getLogger(__name__)


@beartype
def register_auth_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    @router.get("/login")
    async def login_page(request: Request) -> Response:
        return _TEMPLATES.TemplateResponse(
            request,
            "login.html",
            page_context(
                request,
                deps,
                telegram_bot_username=deps.telegram_bot_username,
                stub_login_enabled=deps.stub_login_enabled,
            ),
        )

    @router.post("/auth/telegram")
    async def telegram_auth(request: Request) -> Response:
        fields = await form_fields(request, deps)
        try:
            user_id = verify_telegram_login(
                fields,
                bot_token=deps.bot_token,
                max_age_seconds=deps.telegram_auth_max_age_seconds,
                now_epoch=int(deps.now_factory().timestamp()),
            )
        except TelegramLoginWidgetError:
            _LOGGER.info("admin_login_fail", extra={"reason": "hmac"})
            return Response(status_code=403)
        return complete_login(request, deps, user_id)

    if deps.stub_login_enabled:

        @router.post("/auth/stub")
        async def stub_auth(request: Request) -> Response:
            fields = await form_fields(request, deps)
            raw_id = fields.get("telegram_user_id", "").strip()
            try:
                user_id = int(raw_id)
            except ValueError:
                _LOGGER.info("admin_login_fail", extra={"reason": "stub_id"})
                return Response(status_code=403)
            return complete_login(request, deps, user_id)

    @router.post("/logout")
    async def logout() -> Response:
        response = RedirectResponse(LOGIN_PATH, status_code=303)
        response.delete_cookie(admin_session_cookie_name(), path="/admin")
        return response
