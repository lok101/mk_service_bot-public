from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from urllib.parse import quote

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from starlette.datastructures import Headers, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from src.application.visit_photo_review import (
    ProfileCommandRejected,
    ProfileTechRefStorageError,
    SaveVisitPhotoProfile,
    VisitPhotoProfile,
    VisitPhotoProfileGroup,
    VisitPhotoProfileMember,
    VisitPhotoProfileStore,
    is_service_profile_group,
    seed_service_groups,
)
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    TEMPLATES as _TEMPLATES,
)
from src.interfaces.admin.http_common import (
    form_fields,
    origin_allowed,
    page_context,
    read_admin_body,
    require_panel,
)

_LOGGER = logging.getLogger(__name__)
_LIST_PATH = "/admin/visit-photo-profiles"

_ERROR_TEXT = {
    "profile_member_overlap": "Членство пересекается с другим профилем",
    "members_empty": "Добавьте хотя бы одно членство",
    "unknown_catalog_entry": "Неизвестная модель или тип стойки",
    "stand_not_allowed_for_floor_model": "У напольной модели стойка не нужна",
    "stand_required": "Для ненапольной модели укажите тип стойки",
    "checklist_empty": "Добавьте хотя бы одну содержательную группу",
    "duplicate_group_id": "Дублируется id группы",
    "pack_key_invalid": "Укажите pack_key",
    "catalog_name_invalid": "Укажите название профиля",
    "tech_ref_empty": "Пустой файл tech-ref",
    "tech_ref_type_invalid": "Допустимы только jpg/png/webp",
    "tech_ref_key_invalid": "Некорректный ключ tech-ref",
    "tech_ref_missing": "Файл tech-ref не найден",
    "profile_id_invalid": "Некорректный id профиля",
}


@dataclass(frozen=True, slots=True)
class _ContentGroupRow:
    group_id: str
    title: str


@dataclass(frozen=True, slots=True)
class _CatalogOption:
    entry_id: str
    name: str
    floor_standing: bool | None = None


@dataclass(frozen=True, slots=True)
class _MemberRow:
    model_id: str
    stand_type_id: str


@beartype
def register_visit_photo_profiles_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    store = deps.visit_photo_profile_store
    save = deps.save_visit_photo_profile
    if store is None or save is None:
        return
    tech_storage = deps.visit_photo_profile_tech_ref_storage

    @router.get("/visit-photo-profiles")
    async def profiles_list_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        profiles = await asyncio.to_thread(store.list_all)
        return _TEMPLATES.TemplateResponse(
            request,
            "visit_photo_profiles.html",
            page_context(
                request,
                deps,
                title="Профили фото",
                profiles=sorted(profiles, key=lambda item: item.name.lower()),
                error=_error_text(request.query_params.get("error")),
            ),
        )

    @router.get("/visit-photo-profiles/new")
    async def profiles_new_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        return _editor_page(
            request,
            deps,
            profile=None,
            draft=_empty_draft(),
        )

    @router.post("/visit-photo-profiles/new")
    async def profiles_new_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        fields = await form_fields(request, deps)
        profile_id = uuid.uuid4().hex
        try:
            profile = await asyncio.to_thread(_save_from_fields, save, profile_id, fields)
        except ProfileCommandRejected as exc:
            _LOGGER.info("admin_visit_photo_profile_reject", extra={"code": exc.code})
            return _editor_page(
                request,
                deps,
                profile=None,
                draft=_draft_from_fields(fields),
                error=_error_text(exc.code),
                status_code=400,
            )
        return RedirectResponse(f"{_LIST_PATH}/{profile.profile_id}", status_code=303)

    @router.get("/visit-photo-profiles/{profile_id}")
    async def profiles_edit_get(request: Request, profile_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        profile = await asyncio.to_thread(store.get, profile_id)
        if profile is None:
            return Response(status_code=404)
        return _editor_page(
            request,
            deps,
            profile=profile,
            draft=_draft_from_profile(profile),
        )

    @router.post("/visit-photo-profiles/{profile_id}")
    async def profiles_edit_post(request: Request, profile_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        existing = await asyncio.to_thread(store.get, profile_id)
        if existing is None:
            return Response(status_code=404)
        fields = await form_fields(request, deps)
        if fields.get("action") == "delete":
            await asyncio.to_thread(store.delete, profile_id)
            return RedirectResponse(_LIST_PATH, status_code=303)
        try:
            profile = await asyncio.to_thread(_save_from_fields, save, profile_id, fields)
        except ProfileCommandRejected as exc:
            _LOGGER.info("admin_visit_photo_profile_reject", extra={"code": exc.code})
            return _editor_page(
                request,
                deps,
                profile=existing,
                draft=_draft_from_fields(fields),
                error=_error_text(exc.code),
                status_code=400,
            )
        return RedirectResponse(f"{_LIST_PATH}/{profile.profile_id}", status_code=303)

    @router.post("/visit-photo-profiles/{profile_id}/tech-refs")
    async def profiles_tech_ref_upload(request: Request, profile_id: str) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if tech_storage is None:
            return Response(status_code=404)
        existing = await asyncio.to_thread(store.get, profile_id)
        if existing is None:
            return Response(status_code=404)
        upload = await _extract_tech_ref_file(request, deps)
        if upload is None:
            return RedirectResponse(
                f"{_LIST_PATH}/{profile_id}?error={quote('tech_ref_empty')}",
                status_code=303,
            )
        payload, filename = upload
        try:

            def _upload() -> VisitPhotoProfile:
                key = tech_storage.save(profile_id, filename=filename, payload=payload)
                keys = (*existing.technician_reference_keys, key)
                return save(
                    profile_id=existing.profile_id,
                    name=existing.name,
                    members=existing.members,
                    checklist_items=existing.checklist_items,
                    pack_key=existing.pack_key,
                    technician_reference_keys=keys,
                )

            await asyncio.to_thread(_upload)
        except (ProfileCommandRejected, ProfileTechRefStorageError) as exc:
            code = getattr(exc, "code", "tech_ref_empty")
            return RedirectResponse(
                f"{_LIST_PATH}/{profile_id}?error={quote(str(code))}",
                status_code=303,
            )
        return RedirectResponse(f"{_LIST_PATH}/{profile_id}", status_code=303)

    @router.post("/visit-photo-profiles/{profile_id}/tech-refs/{key}/delete")
    async def profiles_tech_ref_delete(
        request: Request,
        profile_id: str,
        key: str,
    ) -> Response:
        actor = require_panel(request, deps, AdminPanel.VISIT_PHOTO_REVIEW)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        if tech_storage is None:
            return Response(status_code=404)
        existing = await asyncio.to_thread(store.get, profile_id)
        if existing is None:
            return Response(status_code=404)
        try:

            def _delete() -> None:
                tech_storage.delete(profile_id, key)
                keys = tuple(item for item in existing.technician_reference_keys if item != key)
                save(
                    profile_id=existing.profile_id,
                    name=existing.name,
                    members=existing.members,
                    checklist_items=existing.checklist_items,
                    pack_key=existing.pack_key,
                    technician_reference_keys=keys,
                )

            await asyncio.to_thread(_delete)
        except (ProfileCommandRejected, ProfileTechRefStorageError) as exc:
            code = getattr(exc, "code", "tech_ref_missing")
            return RedirectResponse(
                f"{_LIST_PATH}/{profile_id}?error={quote(str(code))}",
                status_code=303,
            )
        return RedirectResponse(f"{_LIST_PATH}/{profile_id}", status_code=303)


def _error_text(code: str | None) -> str | None:
    if code is None or code == "":
        return None
    return _ERROR_TEXT.get(code, code)


@dataclass(frozen=True, slots=True)
class _EditorDraft:
    name: str
    content_groups: tuple[_ContentGroupRow, ...]
    members: tuple[_MemberRow, ...]
    tech_ref_keys: tuple[str, ...]


def _empty_draft() -> _EditorDraft:
    return _EditorDraft(
        name="",
        content_groups=(),
        members=(_MemberRow(model_id="", stand_type_id=""),),
        tech_ref_keys=(),
    )


def _draft_from_profile(profile: VisitPhotoProfile) -> _EditorDraft:
    members = tuple(
        _MemberRow(model_id=m.model_id, stand_type_id=m.stand_type_id or "")
        for m in sorted(profile.members, key=lambda item: (item.model_id, item.stand_type_id or ""))
    )
    if not members:
        members = (_MemberRow(model_id="", stand_type_id=""),)
    content = tuple(
        _ContentGroupRow(group_id=group.group_id, title=group.title)
        for group in profile.groups
        if not is_service_profile_group(group.group_id)
    )
    return _EditorDraft(
        name=profile.name,
        content_groups=content,
        members=members,
        tech_ref_keys=profile.technician_reference_keys,
    )


def _draft_from_fields(fields: dict[str, str]) -> _EditorDraft:
    return _EditorDraft(
        name=fields.get("name", ""),
        content_groups=_content_groups_from_fields(fields),
        members=_member_rows_from_fields(fields) or (_MemberRow(model_id="", stand_type_id=""),),
        tech_ref_keys=(),
    )


def _content_groups_from_fields(fields: dict[str, str]) -> tuple[_ContentGroupRow, ...]:
    rows: list[_ContentGroupRow] = []
    index = 0
    while True:
        id_key = f"content_group_id-{index}"
        title_key = f"content_group_title-{index}"
        if id_key not in fields and title_key not in fields:
            break
        title = fields.get(title_key, "").strip()
        group_id = fields.get(id_key, "").strip()
        if title:
            rows.append(_ContentGroupRow(group_id=group_id, title=title))
        index += 1
    return tuple(rows)


def _member_rows_from_fields(fields: dict[str, str]) -> tuple[_MemberRow, ...]:
    rows: list[_MemberRow] = []
    index = 0
    while True:
        model_key = f"member_model_id-{index}"
        stand_key = f"member_stand_type_id-{index}"
        if model_key not in fields and stand_key not in fields:
            break
        rows.append(
            _MemberRow(
                model_id=fields.get(model_key, "").strip(),
                stand_type_id=fields.get(stand_key, "").strip(),
            )
        )
        index += 1
    return tuple(row for row in rows if row.model_id)


def _save_from_fields(
    save: SaveVisitPhotoProfile,
    profile_id: str,
    fields: dict[str, str],
) -> VisitPhotoProfile:
    members = frozenset(
        VisitPhotoProfileMember(
            model_id=row.model_id,
            stand_type_id=row.stand_type_id or None,
        )
        for row in _member_rows_from_fields(fields)
    )
    content_rows = _content_groups_from_fields(fields)
    content_groups: list[VisitPhotoProfileGroup] = []
    for index, row in enumerate(content_rows, start=1):
        group_id = row.group_id or f"cue-{index}"
        content_groups.append(
            VisitPhotoProfileGroup(
                group_id=group_id,
                title=row.title,
                required=True,
                defects=(),
                photo_only=False,
            )
        )
    existing_refs: tuple[str, ...] = ()
    existing_service: tuple[VisitPhotoProfileGroup, ...] = ()
    store: VisitPhotoProfileStore = save.store
    current = store.get(profile_id)
    if current is not None:
        existing_refs = current.technician_reference_keys
        existing_service = tuple(
            group for group in current.groups if is_service_profile_group(group.group_id)
        )
        pack_key = current.pack_key
    else:
        pack_key = profile_id
    service = existing_service or seed_service_groups()
    return save(
        profile_id=profile_id,
        name=fields.get("name", ""),
        members=members,
        groups=service + tuple(content_groups),
        pack_key=pack_key,
        technician_reference_keys=existing_refs,
    )


def _catalog_options(
    deps: AdminHttpDeps,
) -> tuple[tuple[_CatalogOption, ...], tuple[_CatalogOption, ...]]:
    models: list[_CatalogOption] = []
    stands: list[_CatalogOption] = []
    if deps.coffee_machine_model_store is not None:
        models = [
            _CatalogOption(
                entry_id=model.model_id,
                name=model.name,
                floor_standing=model.floor_standing,
            )
            for model in deps.coffee_machine_model_store.list_all()
        ]
    if deps.stand_type_store is not None:
        stands = [
            _CatalogOption(entry_id=item.stand_type_id, name=item.name)
            for item in deps.stand_type_store.list_all()
        ]
    return tuple(models), tuple(stands)


def _editor_page(
    request: Request,
    deps: AdminHttpDeps,
    *,
    profile: VisitPhotoProfile | None,
    draft: _EditorDraft,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    models, stands = _catalog_options(deps)
    query_error = _error_text(request.query_params.get("error"))
    return _TEMPLATES.TemplateResponse(
        request,
        "visit_photo_profile_editor.html",
        page_context(
            request,
            deps,
            title="Новый профиль фото" if profile is None else draft.name or profile.profile_id,
            is_new=profile is None,
            profile_id=None if profile is None else profile.profile_id,
            draft=draft,
            models=models,
            stand_types=stands,
            error=error or query_error,
            form_action=(
                f"{_LIST_PATH}/new" if profile is None else f"{_LIST_PATH}/{profile.profile_id}"
            ),
        ),
        status_code=status_code,
    )


async def _extract_tech_ref_file(
    request: Request,
    deps: AdminHttpDeps,
) -> tuple[bytes, str] | None:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        return None
    body = await read_admin_body(request, deps)

    async def _stream() -> AsyncGenerator[bytes]:
        yield body

    try:
        form = await MultiPartParser(
            Headers({"content-type": content_type}),
            _stream(),
            max_part_size=max(len(body), 1),
        ).parse()
    except MultiPartException:
        return None
    item = form.get("file")
    if item is None or not isinstance(item, UploadFile):
        return None
    filename = (item.filename or "").strip()
    data = await item.read()
    await item.close()
    if not filename or not data:
        return None
    return data, filename


__all__ = ["register_visit_photo_profiles_routes"]
