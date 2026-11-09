from __future__ import annotations

import asyncio

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from starlette.formparsers import MultiPartException

from src.application.visit_photo_review import ReviewQueries
from src.application.visit_photo_review.ports import CatalogUnavailable
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import origin_allowed, require_panel
from src.interfaces.admin.routes.visit_photo_review_support import (
    avatar_error_message,
    defect_rows_from_fields,
    defects_error_message,
    group_editor_page,
    parse_group_editor_payload,
)

__all__ = ["register_visit_photo_review_mutation_group_routes"]


@beartype
def register_visit_photo_review_mutation_group_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    queries: ReviewQueries,
) -> None:
    @router.get("/visit-photo-review/groups/{group_id}")
    async def visit_photo_review_group_editor_get(
        request: Request,
        group_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        return await group_editor_page(request, deps, queries, group_id=group_id)

    @router.post("/visit-photo-review/groups/{group_id}")
    async def visit_photo_review_group_editor_post(
        request: Request,
        group_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if deps.update_group_defects is None and deps.write_group_avatar is None:
            return Response(status_code=404)
        try:
            fields, photo_bytes, photo_content_type = await parse_group_editor_payload(
                request, deps
            )
        except MultiPartException:
            return await group_editor_page(
                request,
                deps,
                queries,
                group_id=group_id,
                error_message="Некорректное тело формы",
                status_code=400,
            )
        try:
            # Resolve via entry module so tests can monkeypatch `_find_editor_group`.
            from src.interfaces.admin.routes import visit_photo_review as routes_mod

            editor_group = await asyncio.to_thread(routes_mod._find_editor_group, queries, group_id)
        except CatalogUnavailable:
            return Response(status_code=503)
        if editor_group is None:
            return Response(status_code=404)
        photo_present = photo_bytes is not None and len(photo_bytes) > 0
        if photo_present:
            if deps.write_group_avatar is None:
                return await group_editor_page(
                    request,
                    deps,
                    queries,
                    group_id=group_id,
                    error_message="Загрузка фото недоступна",
                    status_code=400,
                )
            assert photo_bytes is not None
            try:
                avatar_result = await asyncio.to_thread(
                    deps.write_group_avatar.execute,
                    group_id=group_id,
                    content=photo_bytes,
                    content_type=photo_content_type or "application/octet-stream",
                )
            except CatalogUnavailable:
                return Response(status_code=503)
            if avatar_result.is_err():
                return await group_editor_page(
                    request,
                    deps,
                    queries,
                    group_id=group_id,
                    error_message=avatar_error_message(avatar_result.error),
                    status_code=400,
                )
        if not editor_group.photo_only:
            if deps.update_group_defects is None:
                return Response(status_code=404)
            rows = defect_rows_from_fields(fields)
            try:
                defects_result = await asyncio.to_thread(
                    deps.update_group_defects.execute,
                    group_id,
                    rows,
                )
            except CatalogUnavailable:
                return Response(status_code=503)
            if defects_result.is_err():
                return await group_editor_page(
                    request,
                    deps,
                    queries,
                    group_id=group_id,
                    error_message=defects_error_message(defects_result.error),
                    status_code=400,
                )
        return RedirectResponse(
            f"/admin/visit-photo-review/groups/{group_id}",
            status_code=303,
        )
