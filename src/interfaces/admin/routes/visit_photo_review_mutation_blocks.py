from __future__ import annotations

import asyncio
from typing import Any

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from src.application.visit_photo_grouping import DisposeAction
from src.application.visit_photo_review import (
    UNRECOGNIZED_GROUP_ID,
    RecordFrameView,
    ReviewQueries,
)
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import form_fields, origin_allowed, require_panel
from src.interfaces.admin.routes.visit_photo_review_support import (
    LIST_PATH,
    LOGGER,
    after_close_target,
    dispose_error_response,
    filters_from_request,
    mark_error_response,
    query_string,
    review_submit_action,
    save_error_response,
)
from src.interfaces.admin.routes.visit_photo_review_support import (
    wants_json as request_wants_json,
)

__all__ = ["register_visit_photo_review_mutation_block_routes"]


@beartype
def register_visit_photo_review_mutation_block_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    queries: ReviewQueries,
    store: Any,
    record_frame_view: RecordFrameView,
) -> None:
    @router.post("/visit-photo-review/blocks/{batch_id}/unrecognized/dispose")
    async def visit_photo_review_dispose(
        request: Request,
        batch_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            LOGGER.info(
                "admin_visit_photo_review_origin_reject",
                extra={"batch_id": batch_id, "group_id": UNRECOGNIZED_GROUP_ID},
            )
            return Response(status_code=403)
        if deps.dispose_unrecognized_index is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        try:
            index = int(fields.get("index", ""))
        except ValueError:
            return Response(status_code=422)
        action_raw = fields.get("action", "").strip()
        try:
            action = DisposeAction(action_raw)
        except ValueError:
            return Response(status_code=422)
        target_raw = fields.get("target_group_id", "").strip()
        target_group_id = target_raw or None
        result = await asyncio.to_thread(
            deps.dispose_unrecognized_index.execute,
            batch_id,
            index,
            action,
            target_group_id,
        )
        wants_json = request_wants_json(request)
        if result.is_err():
            return dispose_error_response(result.error, wants_json=wants_json)
        remaining = await asyncio.to_thread(store.find_assignment, batch_id, UNRECOGNIZED_GROUP_ID)
        remaining_indexes = list(remaining.indexes) if remaining is not None else []
        if wants_json:
            return JSONResponse({"ok": True, "remaining_indexes": remaining_indexes})
        day_raw = request.query_params.get("day", "all")
        filters = filters_from_request(request, day_raw=day_raw)
        if remaining_indexes:
            return RedirectResponse(
                f"/admin/visit-photo-review/blocks/{batch_id}/{UNRECOGNIZED_GROUP_ID}"
                f"?{query_string(filters)}",
                status_code=303,
            )
        return RedirectResponse(f"{LIST_PATH}?{query_string(filters)}", status_code=303)

    @router.post("/visit-photo-review/blocks/{batch_id}/{group_id}")
    async def visit_photo_review_block_post(
        request: Request,
        batch_id: str,
        group_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            LOGGER.info(
                "admin_visit_photo_review_origin_reject",
                extra={"batch_id": batch_id, "group_id": group_id},
            )
            return Response(status_code=403)
        if deps.save_review_record is None or deps.clear_review_record is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        raw_index = fields.get("index", "").strip()
        if not raw_index:
            return JSONResponse({"error": "Нет индекса кадра"}, status_code=422)
        try:
            frame_index = int(raw_index)
        except ValueError:
            return JSONResponse({"error": "Нет индекса кадра"}, status_code=422)
        defect_codes = tuple(
            key.removeprefix("defect-")
            for key, value in fields.items()
            if key.startswith("defect-") and value
        )
        system_error = bool(fields.get("system_error"))
        comment = fields.get("comment", "")
        has_record = (
            await asyncio.to_thread(store.find_frame_record, batch_id, group_id, frame_index)
            is not None
        )
        action = review_submit_action(
            defect_codes=defect_codes,
            system_error=system_error,
            has_record=has_record,
        )
        if action == "save":
            result = await asyncio.to_thread(
                deps.save_review_record.execute,
                actor_user_id=str(actor),
                batch_id=batch_id,
                group_id=group_id,
                defect_codes=defect_codes,
                system_error=system_error,
                comment=comment,
                frame_index=frame_index,
            )
            if result.is_err():
                LOGGER.info(
                    "visit_photo_review.save rejected",
                    extra={"batch_id": batch_id, "group_id": group_id},
                )
                return save_error_response(result.error)
        elif action == "clear":
            await asyncio.to_thread(
                deps.clear_review_record.execute,
                batch_id,
                group_id,
                frame_index=frame_index,
            )
        day_raw = request.query_params.get("day", "all")
        filters = filters_from_request(request, day_raw=day_raw)
        return RedirectResponse(
            await after_close_target(
                queries,
                batch_id,
                group_id,
                filters,
                timezone=deps.timezone,
                day_end_hour=deps.day_end_hour,
            ),
            303,
        )

    @router.post("/visit-photo-review/blocks/{batch_id}/{group_id}/clear")
    async def visit_photo_review_block_clear(
        request: Request,
        batch_id: str,
        group_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if deps.clear_review_record is None:
            return Response(status_code=404)
        await asyncio.to_thread(deps.clear_review_record.execute, batch_id, group_id)
        day_raw = request.query_params.get("day", "all")
        filters = filters_from_request(request, day_raw=day_raw)
        return RedirectResponse(
            await after_close_target(
                queries,
                batch_id,
                group_id,
                filters,
                timezone=deps.timezone,
                day_end_hour=deps.day_end_hour,
            ),
            303,
        )

    @router.post("/visit-photo-review/frames/{batch_id}/{index}/view")
    async def visit_photo_review_frame_view(
        request: Request,
        batch_id: str,
        index: int,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        await asyncio.to_thread(
            record_frame_view.execute,
            batch_id=batch_id,
            index=index,
            actor_user_id=str(actor),
        )
        return Response(status_code=204)

    @router.post("/visit-photo-review/blocks/{batch_id}/{group_id}/mark")
    async def visit_photo_review_instant_mark(
        request: Request,
        batch_id: str,
        group_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if deps.save_review_record is None or deps.clear_review_record is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        defect_code = fields.get("defect_code", "").strip()
        toggle_system = fields.get("system_error", "").strip() in {"1", "on", "true"}
        if not defect_code and not toggle_system:
            return JSONResponse({"error": "Нет кода отметки"}, status_code=422)
        raw_index = fields.get("index", "").strip()
        if not raw_index:
            return JSONResponse({"error": "Нет индекса кадра"}, status_code=422)
        try:
            frame_index = int(raw_index)
        except ValueError:
            return JSONResponse({"error": "Нет индекса кадра"}, status_code=422)
        existing = await asyncio.to_thread(store.find_frame_record, batch_id, group_id, frame_index)
        codes = (
            {mark.code for mark in existing.defects}
            if existing is not None and existing.record_kind == "human"
            else set()
        )
        system_error = bool(existing is not None and existing.system_error)
        comment = existing.comment if existing is not None else ""
        if defect_code:
            if defect_code in codes:
                codes.discard(defect_code)
            else:
                codes.add(defect_code)
        if toggle_system:
            system_error = not system_error
        if not codes and not system_error:
            if existing is not None:
                await asyncio.to_thread(
                    deps.clear_review_record.execute,
                    batch_id,
                    group_id,
                    frame_index=frame_index,
                )
            return JSONResponse(
                {"ok": True, "defect_codes": [], "system_error": False, "cleared": True}
            )
        result = await asyncio.to_thread(
            deps.save_review_record.execute,
            actor_user_id=str(actor),
            batch_id=batch_id,
            group_id=group_id,
            defect_codes=tuple(sorted(codes)),
            system_error=system_error,
            comment=comment,
            frame_index=frame_index,
        )
        if result.is_err():
            LOGGER.info(
                "visit_photo_review.instant_mark rejected",
                extra={"batch_id": batch_id, "group_id": group_id},
            )
            return mark_error_response(result.error)
        saved = result.value
        return JSONResponse(
            {
                "ok": True,
                "defect_codes": [mark.code for mark in saved.defects],
                "system_error": saved.system_error,
                "cleared": False,
            }
        )
