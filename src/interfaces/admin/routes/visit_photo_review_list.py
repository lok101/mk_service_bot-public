from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlencode

from beartype import beartype
from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from src.application.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
    ReviewQueries,
)
from src.application.visit_photo_review.ports import CatalogUnavailable
from src.domain.calendar import operational_day
from src.domain.system_user import AdminPanel
from src.interfaces.admin.clock_display import format_admin_moment
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import page_context, require_panel
from src.interfaces.admin.routes.visit_photo_review_support import (
    LIST_PATH,
    TEMPLATES,
    FilterDefect,
    FilterGroup,
    block_labels,
    catalog_group_rows,
    choice_rows,
    content_filter_groups,
    day_display,
    day_iso_for_picker,
    facet_labels,
    filters_from_request,
    json_for_script,
    matching_defect_code,
    problem_options,
    query_string,
)
from src.interfaces.admin.routes.visit_photo_review_support import (
    active_tab as resolve_active_tab,
)

__all__ = ["render_visit_photo_review_list_page"]


@beartype
async def render_visit_photo_review_list_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    queries: ReviewQueries,
    catalog_source: Any,
    store: Any,
) -> Response:
    actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
    if isinstance(actor, Response):
        return actor
    day_raw = request.query_params.get("day")
    if day_raw is None:
        today = operational_day(deps.now_factory(), deps.timezone, deps.day_end_hour)
        return RedirectResponse(
            f"{LIST_PATH}?{urlencode({'day': today.isoformat()})}",
            status_code=303,
        )
    filters = filters_from_request(request, day_raw=day_raw)
    active_tab = resolve_active_tab(request)
    try:
        catalog = await asyncio.to_thread(catalog_source.load)
        groups = await asyncio.to_thread(
            queries.list_queue_groups,
            day=filters.day,
            timezone=deps.timezone,
            day_end_hour=deps.day_end_hour,
            machine_id=filters.machine_id,
            technician_id=filters.technician_id,
            view_filter=filters.view_filter,
        )
        editor_groups = await asyncio.to_thread(queries.list_catalog_editor_groups)
    except CatalogUnavailable:
        return Response(status_code=503)
    reserved = {UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID}
    content_groups = tuple(
        {"group_id": item.group_id, "title": item.title}
        for item in catalog.groups
        if item.group_id not in reserved
    )
    catalog_groups = await asyncio.to_thread(
        catalog_group_rows,
        editor_groups,
        deps.group_avatar_reader,
    )
    tiles: list[dict[str, object]] = []
    carousel_payload: list[dict[str, object]] = []
    for group in groups:
        catalog_group = catalog.group(group.group_id)
        title = catalog_group.title if catalog_group is not None else group.group_id
        defects = (
            tuple({"code": button.code, "label": button.label} for button in catalog_group.defects)
            if catalog_group is not None
            else ()
        )
        frames: list[dict[str, object]] = []
        for frame in group.frames:
            labels = block_labels(deps, frame.machine_id, frame.technician_id)
            record = store.find_frame_record(frame.batch_id, group.group_id, frame.index)
            selected_codes = (
                sorted(mark.code for mark in record.defects)
                if record is not None and record.record_kind == "human"
                else []
            )
            system_error = bool(record is not None and record.system_error)
            frames.append(
                {
                    "batch_id": frame.batch_id,
                    "index": frame.index,
                    "occurred_at": frame.occurred_at.isoformat(),
                    "machine_id": frame.machine_id,
                    "technician_id": frame.technician_id,
                    "machine_name": labels["machine_name"],
                    "technician_name": labels["technician_name"],
                    "photo_href": (
                        f"/admin/visit-photo-review/photos/{frame.batch_id}/{frame.index}"
                    ),
                    "selected_codes": selected_codes,
                    "system_error": system_error,
                }
            )
        if not frames:
            continue
        is_unrecognized = group.group_id == UNRECOGNIZED_GROUP_ID
        tiles.append(
            {
                "group_id": group.group_id,
                "title": title,
                "is_missing": False,
                "frame_count": len(frames),
                "avatar_href": (
                    f"/admin/visit-photo-review/avatars/{group.group_id}"
                    if deps.group_avatar_reader is not None
                    else ""
                ),
            }
        )
        carousel_payload.append(
            {
                "group_id": group.group_id,
                "title": title,
                "is_missing": False,
                "is_unrecognized": is_unrecognized,
                "defects": list(defects),
                "content_groups": list(content_groups),
                "frames": frames,
            }
        )
    # Always load rows so client-side tab switch (replaceState) shows data
    # without a full reload — same pattern as catalog_groups on every tab.
    day_raw_for_query: str | None
    if filters.day is not None:
        day_raw_for_query = None
    elif filters.day_raw == "all":
        day_raw_for_query = "all"
    else:
        day_raw_for_query = filters.day_raw
    selected_group = catalog.group(filters.group_id) if filters.group_id else None
    filters.defect_query = (
        matching_defect_code(selected_group, filters.defect_query) if filters.group_id else None
    )
    filter_groups = content_filter_groups(catalog)
    if filters.group_id and all(item.group_id != filters.group_id for item in filter_groups):
        filter_groups.append(
            FilterGroup(
                group_id=filters.group_id,
                title=selected_group.title if selected_group is not None else filters.group_id,
                defects=tuple(
                    FilterDefect(code=defect.code, label=defect.label)
                    for defect in (selected_group.defects if selected_group else ())
                ),
            )
        )
        filter_groups.sort(key=lambda item: item.title.casefold())
    facet_list = await asyncio.to_thread(
        queries.list_problem_rows,
        day=filters.day,
        timezone=deps.timezone,
        day_end_hour=deps.day_end_hour,
        day_raw=day_raw_for_query,
        offset=0,
        page_size=None,
    )
    problem_list = await asyncio.to_thread(
        queries.list_problem_rows,
        day=filters.day,
        timezone=deps.timezone,
        day_end_hour=deps.day_end_hour,
        group_id=filters.group_id,
        machine_id=filters.machine_id,
        technician_id=filters.technician_id,
        defect_query=filters.defect_query,
        day_raw=day_raw_for_query,
        offset=filters.offset,
    )
    problem_rows: list[dict[str, object]] = []
    for row in problem_list.items:
        labels = block_labels(deps, row.machine_id, row.technician_id)
        photo_ref = await asyncio.to_thread(queries.read_photo, row.batch_id, row.photo_index)
        has_photo = photo_ref is not None
        location = labels["location_name"] or labels["machine_name"] or "—"
        problem_rows.append(
            {
                "batch_id": row.batch_id,
                "group_id": row.group_id,
                "photo_index": row.photo_index,
                "occurred_at_label": format_admin_moment(row.occurred_at, deps.timezone),
                "location_name": location,
                "technician_name": labels["technician_name"] or "—",
                "group_title": row.group_title or row.group_id,
                "defect_label": row.defect_label or row.defect_code,
                "photo_href": (
                    f"/admin/visit-photo-review/photos/{row.batch_id}/{row.photo_index}"
                    if has_photo
                    else ""
                ),
                "has_photo": has_photo,
            }
        )

    return TEMPLATES.TemplateResponse(
        request,
        "visit_photo_review.html",
        page_context(
            request,
            deps,
            tiles=tiles,
            carousel_groups_json=json.dumps(carousel_payload, ensure_ascii=False),
            filters=filters,
            query_string=query_string(filters),
            active_tab=active_tab,
            catalog_groups=catalog_groups,
            problem_rows=problem_rows,
            day_display=day_display(filters.day_raw),
            day_iso=day_iso_for_picker(filters.day_raw),
            location_options=choice_rows(
                facet_labels(
                    deps,
                    facet_list.items,
                    key="machine_id",
                    label_keys=("location_name", "machine_name"),
                    selected_id=filters.machine_id,
                )
            ),
            technician_options=choice_rows(
                facet_labels(
                    deps,
                    facet_list.items,
                    key="technician_id",
                    label_keys=("technician_name",),
                    selected_id=filters.technician_id,
                )
            ),
            filter_groups=filter_groups,
            filter_groups_json=json_for_script(
                [
                    {
                        "group_id": group.group_id,
                        "title": group.title,
                        "defects": [
                            {"code": defect.code, "label": defect.label} for defect in group.defects
                        ],
                    }
                    for group in filter_groups
                ]
            ),
            problem_options=problem_options(filter_groups, filters.group_id),
            problem_filter_enabled=filters.group_id is not None,
        ),
    )
