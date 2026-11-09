from __future__ import annotations

import asyncio
import json
from typing import Literal
from zoneinfo import ZoneInfo

from beartype import beartype
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from src.application.visit_photo_grouping import DisposeError
from src.application.visit_photo_review import ReviewQueries
from src.application.visit_photo_review.ports import ReviewLabels
from src.domain.visit_photo_review import SaveError
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.visit_photo_review_filters import Filters, query_string

LIST_PATH = "/admin/visit-photo-review"

__all__ = [
    "after_close_target",
    "block_labels",
    "dispose_error_response",
    "json_for_script",
    "mark_error_response",
    "review_submit_action",
    "save_error_response",
    "wants_json",
]


@beartype
def review_submit_action(
    *,
    defect_codes: tuple[str, ...],
    system_error: bool,
    has_record: bool,
) -> Literal["save", "clear", "skip"]:
    if defect_codes or system_error:
        return "save"
    if has_record:
        return "clear"
    return "skip"


@beartype
def block_labels(deps: AdminHttpDeps, machine_id: str, technician_id: str) -> dict[str, str]:
    lookup = deps.review_label_lookup
    if lookup is None:
        return {
            "machine_name": machine_id,
            "location_name": "",
            "technician_name": technician_id,
        }
    labels: ReviewLabels = lookup.labels_for(machine_id, technician_id)
    return {
        "machine_name": labels.machine_name or machine_id,
        "location_name": labels.location_name or "",
        "technician_name": labels.technician_name or technician_id,
    }


@beartype
def save_error_response(error: SaveError) -> Response:
    match error:
        case SaveError.NO_LIVE_ASSIGNMENT:
            return Response(status_code=409)
        case SaveError.NO_MARKS | SaveError.UNKNOWN_DEFECT | SaveError.INVALID_FRAME_INDEX:
            return Response(status_code=422)
        case SaveError.CATALOG_UNAVAILABLE:
            return Response(status_code=503)


@beartype
def mark_error_response(error: SaveError) -> Response:
    match error:
        case SaveError.NO_LIVE_ASSIGNMENT:
            return JSONResponse(
                {"error": "Нет живого назначения для записи"},
                status_code=409,
            )
        case SaveError.NO_MARKS:
            return JSONResponse({"error": "Нет отметок для записи"}, status_code=422)
        case SaveError.UNKNOWN_DEFECT:
            return JSONResponse({"error": "Неизвестный код изъяна"}, status_code=422)
        case SaveError.INVALID_FRAME_INDEX:
            return JSONResponse({"error": "Кадр не в этой группе"}, status_code=422)
        case SaveError.CATALOG_UNAVAILABLE:
            return JSONResponse({"error": "Каталог недоступен"}, status_code=503)


@beartype
def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


@beartype
def dispose_error_response(error: DisposeError, *, wants_json: bool = False) -> Response:
    if wants_json:
        match error:
            case DisposeError.BATCH_NOT_ACCEPTED:
                return JSONResponse({"error": "Пакет не найден"}, status_code=404)
            case DisposeError.INDEX_WITHOUT_FILE:
                return JSONResponse({"error": "Нет файла кадра"}, status_code=422)
            case DisposeError.INVALID_TARGET:
                return JSONResponse({"error": "Недопустимая целевая группа"}, status_code=422)
            case DisposeError.RELOCATE_FAILED:
                return JSONResponse({"error": "Не удалось перенести кадр"}, status_code=422)
            case DisposeError.INDEX_NOT_IN_UNRECOGNIZED:
                return JSONResponse(
                    {"error": "Кадр уже не в неразобранных"},
                    status_code=409,
                )
            case DisposeError.CATALOG_UNAVAILABLE:
                return JSONResponse({"error": "Каталог недоступен"}, status_code=503)
    match error:
        case DisposeError.BATCH_NOT_ACCEPTED:
            return Response(status_code=404)
        case (
            DisposeError.INDEX_WITHOUT_FILE
            | DisposeError.INVALID_TARGET
            | DisposeError.RELOCATE_FAILED
        ):
            return Response(status_code=422)
        case DisposeError.INDEX_NOT_IN_UNRECOGNIZED:
            return Response(status_code=409)
        case DisposeError.CATALOG_UNAVAILABLE:
            return Response(status_code=503)


@beartype
async def after_close_target(
    queries: ReviewQueries,
    batch_id: str,
    group_id: str,
    filters: Filters,
    *,
    timezone: ZoneInfo,
    day_end_hour: int,
) -> str:
    adjacent = await asyncio.to_thread(
        queries.adjacent_block,
        current_batch_id=batch_id,
        current_group_id=group_id,
        day=filters.day,
        timezone=timezone,
        day_end_hour=day_end_hour,
        group_id=filters.group_id,
        machine_id=filters.machine_id,
        technician_id=filters.technician_id,
        offset=filters.offset,
    )
    if adjacent.next_batch_id is not None and adjacent.next_group_id is not None:
        return (
            f"/admin/visit-photo-review/blocks/"
            f"{adjacent.next_batch_id}/{adjacent.next_group_id}"
            f"?{query_string(filters)}"
        )
    return f"{LIST_PATH}?{query_string(filters)}"


@beartype
def json_for_script(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
