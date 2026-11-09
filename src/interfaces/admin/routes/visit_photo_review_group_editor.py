from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from beartype import beartype
from fastapi import Request
from fastapi.responses import Response
from starlette.datastructures import Headers, UploadFile
from starlette.formparsers import MultiPartParser

from src.application.visit_photo_review import (
    CatalogEditorGroup,
    ReviewQueries,
    UpdateGroupDefectsError,
    WriteGroupAvatarError,
)
from src.application.visit_photo_review.ports import CatalogUnavailable, GroupAvatarReader
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import TEMPLATES, form_fields, page_context, read_admin_body

LIST_PATH = "/admin/visit-photo-review"

__all__ = [
    "avatar_error_message",
    "catalog_group_rows",
    "defect_rows_from_fields",
    "defects_error_message",
    "find_editor_group",
    "group_editor_page",
    "parse_group_editor_payload",
]


@beartype
def catalog_group_rows(
    editor_groups: tuple[CatalogEditorGroup, ...],
    reader: GroupAvatarReader | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in editor_groups:
        has_avatar = False
        if reader is not None:
            has_avatar = reader.read_avatar(item.group_id) is not None
        rows.append(
            {
                "group_id": item.group_id,
                "title": item.title,
                "photo_only": item.photo_only,
                "has_avatar": has_avatar,
            }
        )
    return rows


@beartype
def find_editor_group(queries: ReviewQueries, group_id: str) -> CatalogEditorGroup | None:
    for item in queries.list_catalog_editor_groups():
        if item.group_id == group_id:
            return item
    return None


@beartype
async def group_editor_page(
    request: Request,
    deps: AdminHttpDeps,
    queries: ReviewQueries,
    *,
    group_id: str,
    error_message: str | None = None,
    status_code: int = 200,
) -> Response:
    try:
        editor_group = await asyncio.to_thread(find_editor_group, queries, group_id)
    except CatalogUnavailable:
        return Response(status_code=503)
    if editor_group is None:
        return Response(status_code=404)
    has_avatar = False
    reader = deps.group_avatar_reader
    if reader is not None:
        has_avatar = await asyncio.to_thread(reader.read_avatar, group_id) is not None
    return TEMPLATES.TemplateResponse(
        request,
        "visit_photo_review_group_editor.html",
        page_context(
            request,
            deps,
            group_id=group_id,
            group_title=editor_group.title,
            photo_only=editor_group.photo_only,
            defects=editor_group.defects,
            has_avatar=has_avatar,
            error_message=error_message,
            groups_list_href=f"{LIST_PATH}?tab=groups",
        ),
        status_code=status_code,
    )


@beartype
def defect_rows_from_fields(fields: dict[str, str]) -> tuple[tuple[str, str], ...]:
    indexes: set[int] = set()
    for key in fields:
        if key.startswith("defect_code_"):
            suffix = key.removeprefix("defect_code_")
            if suffix.isdigit():
                indexes.add(int(suffix))
        elif key.startswith("defect_label_"):
            suffix = key.removeprefix("defect_label_")
            if suffix.isdigit():
                indexes.add(int(suffix))
    rows: list[tuple[str, str]] = []
    for index in sorted(indexes):
        code = fields.get(f"defect_code_{index}", "")
        label = fields.get(f"defect_label_{index}", "")
        rows.append((code, label))
    return tuple(rows)


@beartype
def avatar_error_message(error: WriteGroupAvatarError) -> str:
    match error:
        case WriteGroupAvatarError.INVALID_IMAGE:
            return "Некорректный файл изображения"
        case WriteGroupAvatarError.PACK_DIR_UNAVAILABLE:
            return "Каталог фото групп недоступен"
        case WriteGroupAvatarError.UNSAFE_GROUP_ID:
            return "Недопустимый идентификатор группы"


@beartype
def defects_error_message(error: UpdateGroupDefectsError) -> str:
    match error:
        case UpdateGroupDefectsError.DUPLICATE_CODE:
            return "Дублирующийся код проблемы"
        case UpdateGroupDefectsError.PHOTO_ONLY_GROUP:
            return "У этой группы нельзя менять проблемы"
        case UpdateGroupDefectsError.UNKNOWN_GROUP:
            return "Группа не найдена"


@beartype
async def parse_group_editor_payload(
    request: Request,
    deps: AdminHttpDeps,
) -> tuple[dict[str, str], bytes | None, str | None]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        return await form_fields(request, deps), None, None
    body = await read_admin_body(request, deps)

    async def _stream() -> AsyncGenerator[bytes]:
        yield body

    parser = MultiPartParser(
        Headers({"content-type": content_type}),
        _stream(),
        max_part_size=max(len(body), 1),
    )
    form = await parser.parse()
    fields: dict[str, str] = {}
    photo_bytes: bytes | None = None
    photo_content_type: str | None = None
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            if key == "photo":
                filename = (value.filename or "").strip()
                data = await value.read()
                await value.close()
                if filename and data:
                    photo_bytes = data
                    photo_content_type = value.content_type
            else:
                await value.close()
            continue
        fields[str(key)] = str(value)
    return fields, photo_bytes, photo_content_type
