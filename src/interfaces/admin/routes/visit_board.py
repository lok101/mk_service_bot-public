from __future__ import annotations

import asyncio

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import TEMPLATES as _TEMPLATES
from src.interfaces.admin.http_common import page_context, require_panel
from src.interfaces.admin.page_builders import build_visit_board_page_sync

_VISIT_BOARD_PATH = "/admin/visit-board"

__all__ = ["register_visit_board_routes"]


@beartype
def register_visit_board_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    if deps.master_stores is None or deps.build_visit_board is None:
        return

    @router.get("/visit-board")
    async def visit_board_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_BOARD)
        if isinstance(actor, Response):
            return actor
        if deps.build_visit_board is None or deps.master_stores is None:
            return Response(status_code=404)
        now = deps.now_factory()
        payload = await asyncio.to_thread(
            build_visit_board_page_sync,
            deps,
            year_raw=request.query_params.get("year"),
            month_raw=request.query_params.get("month"),
            now=now,
            visit_board_path=_VISIT_BOARD_PATH,
        )
        if payload.redirect is not None:
            return RedirectResponse(payload.redirect, status_code=303)
        return _TEMPLATES.TemplateResponse(
            request,
            "visit_board.html",
            page_context(request, deps, board=payload.board),
        )
