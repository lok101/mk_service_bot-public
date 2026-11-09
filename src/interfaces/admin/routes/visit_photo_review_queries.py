from __future__ import annotations

import asyncio
from typing import Any

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import Response

from src.application.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
    ReviewQueries,
)
from src.application.visit_photo_review.ports import CatalogUnavailable
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import origin_allowed, page_context, require_panel
from src.interfaces.admin.routes.visit_photo_review_support import (
    LIST_PATH,
    LOGGER,
    TEMPLATES,
    block_labels,
    filters_from_request,
    query_string,
)

__all__ = ["register_visit_photo_review_query_routes"]


@beartype
def register_visit_photo_review_query_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    queries: ReviewQueries,
    catalog_source: Any,
    store: Any,
) -> None:

    @router.get("/visit-photo-review")
    @router.get("/visit-photo-review")
    async def visit_photo_review_list(request: Request) -> Response:
        from src.interfaces.admin.routes.visit_photo_review_list import (
            render_visit_photo_review_list_page,
        )

        return await render_visit_photo_review_list_page(
            request,
            deps,
            queries=queries,
            catalog_source=catalog_source,
            store=store,
        )

    @router.get("/visit-photo-review/blocks/{batch_id}/{group_id}")
    async def visit_photo_review_block_get(
        request: Request,
        batch_id: str,
        group_id: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        day_raw = request.query_params.get("day", "all")
        filters = filters_from_request(request, day_raw=day_raw)
        try:
            catalog = await asyncio.to_thread(catalog_source.load)
        except CatalogUnavailable:
            return Response(status_code=503)
        assignment = await asyncio.to_thread(store.find_assignment, batch_id, group_id)
        record = await asyncio.to_thread(store.find_record, batch_id, group_id)
        if assignment is None and record is None:
            return Response(status_code=404)
        if assignment is not None:
            indexes = assignment.indexes
            machine_id = assignment.machine_id
            technician_id = assignment.technician_id
        else:
            assert record is not None
            indexes = record.indexes
            machine_id = record.machine_id
            technician_id = record.technician_id
        catalog_group = catalog.group(group_id)
        adjacent = await asyncio.to_thread(
            queries.adjacent_block,
            current_batch_id=batch_id,
            current_group_id=group_id,
            day=filters.day,
            timezone=deps.timezone,
            day_end_hour=deps.day_end_hour,
            group_id=filters.group_id,
            machine_id=filters.machine_id,
            technician_id=filters.technician_id,
            offset=filters.offset,
        )
        selected_codes = (
            {mark.code for mark in record.defects}
            if record is not None and record.record_kind == "human"
            else set()
        )
        system_error = bool(record is not None and record.system_error)
        comment = record.comment if record is not None else ""
        can_save = assignment is not None and bool(assignment.indexes)
        is_unrecognized = group_id == UNRECOGNIZED_GROUP_ID
        reserved = {UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID}
        content_groups = tuple(
            {"group_id": item.group_id, "title": item.title}
            for item in catalog.groups
            if item.group_id not in reserved
        )
        labels = block_labels(deps, machine_id, technician_id)
        group_title = group_id
        if catalog_group is not None:
            group_title = catalog_group.title
        elif record is not None:
            group_title = record.group_title
        return TEMPLATES.TemplateResponse(
            request,
            "visit_photo_review_block.html",
            page_context(
                request,
                deps,
                batch_id=batch_id,
                group_id=group_id,
                indexes=indexes,
                defects=() if catalog_group is None else catalog_group.defects,
                selected_codes=selected_codes,
                system_error=system_error,
                comment=comment,
                can_save=can_save,
                has_record=record is not None,
                is_unrecognized=is_unrecognized,
                content_groups=content_groups,
                group_title=group_title,
                adjacent=adjacent,
                filters=filters,
                query_string=query_string(filters),
                list_href=f"{LIST_PATH}?{query_string(filters)}",
                machine_id=machine_id,
                technician_id=technician_id,
                **labels,
            ),
        )

    @router.get("/visit-photo-review/photos/{batch_id}/{index}")
    async def visit_photo_review_photo(
        request: Request,
        batch_id: str,
        index: int,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        ref = await asyncio.to_thread(queries.read_photo, batch_id, index)
        if ref is None or deps.photo_storage is None:
            return Response(status_code=404)
        try:
            payload = await deps.photo_storage.get_bytes(ref.storage_key)
        except Exception:
            LOGGER.info(
                "visit_photo_review.photo_read_failed",
                extra={"batch_id": batch_id, "group_id": ""},
            )
            return Response(status_code=404)
        return Response(content=payload, media_type=ref.content_type)

    @router.get("/visit-photo-review/avatars/{group_id}")
    async def visit_photo_review_avatar(request: Request, group_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        reader = deps.group_avatar_reader
        if reader is None:
            return Response(status_code=404)
        avatar = await asyncio.to_thread(reader.read_avatar, group_id)
        if avatar is None:
            return Response(status_code=404)
        return Response(content=avatar.content, media_type=avatar.content_type)
