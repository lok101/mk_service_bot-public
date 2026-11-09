from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import quote

from beartype import beartype
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from src.application.master_data import (
    CoffeeEquipmentCatalogs,
    CoffeeEquipmentCommands,
    MasterDataCommandRejected,
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
    require_panel,
)

_LOGGER = logging.getLogger(__name__)

_ERROR_TEXT = {
    "catalog_name_invalid": "Имя пустое или уже есть в этом справочнике",
    "catalog_entry_in_use": "Строка используется на карточке аппарата",
    "floor_standing_blocked_by_stand": "Нельзя включить напольность, пока на карточках есть стойка",
    "unknown_catalog_entry": "Строка справочника не найдена",
    "stand_not_allowed": "Стойка без модели не сохраняется",
    "equipment_catalog_not_for_kind": "Справочник модели и стойки только для кофе",
}


@dataclass(frozen=True, slots=True)
class _CatalogRow:
    entry_id: str
    name: str
    floor_standing: bool | None


@beartype
def equipment_catalogs(deps: AdminHttpDeps) -> CoffeeEquipmentCatalogs | None:
    models = deps.coffee_machine_model_store
    stand_types = deps.stand_type_store
    stand_colors = deps.stand_color_store
    if models is None or stand_types is None or stand_colors is None:
        return None
    return CoffeeEquipmentCatalogs(
        models=models,
        stand_types=stand_types,
        stand_colors=stand_colors,
    )


def catalog_error_text(code: str | None) -> str | None:
    if code is None or code == "":
        return None
    return _ERROR_TEXT.get(code, code)


@beartype
def register_coffee_equipment_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    _register_named(
        router,
        deps,
        path="/coffee-machine-models",
        title="Модели кофемашин",
        show_floor=True,
        kind="model",
    )
    _register_named(
        router,
        deps,
        path="/stand-types",
        title="Типы стоек",
        show_floor=False,
        kind="stand_type",
    )
    _register_named(
        router,
        deps,
        path="/stand-colors",
        title="Цвета стоек",
        show_floor=False,
        kind="stand_color",
    )


def _register_named(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    path: str,
    title: str,
    show_floor: bool,
    kind: str,
) -> None:
    async def catalog_get(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        catalogs = equipment_catalogs(deps)
        if catalogs is None or deps.master_stores is None:
            return Response(status_code=404)
        rows = await asyncio.to_thread(_rows, catalogs, kind)
        error = catalog_error_text(request.query_params.get("error"))
        return _TEMPLATES.TemplateResponse(
            request,
            "coffee_equipment_catalog.html",
            page_context(
                request,
                deps,
                title=title,
                rows=rows,
                show_floor=show_floor,
                form_action=f"/admin{path}",
                error=error,
            ),
        )

    catalog_get.__name__ = f"coffee_equipment_{kind}_get"
    router.get(path)(catalog_get)

    async def catalog_post(request: Request) -> Response:
        actor = require_panel(request, deps, AdminPanel.MASTER_DATA)
        if isinstance(actor, Response):
            return actor
        if not origin_allowed(request):
            return Response(status_code=403)
        catalogs = equipment_catalogs(deps)
        stores = deps.master_stores
        if catalogs is None or stores is None:
            return Response(status_code=404)
        assert isinstance(actor, int)
        fields = await form_fields(request, deps)
        intent = fields.get("intent", "")

        def _apply() -> None:
            commands = CoffeeEquipmentCommands(
                stores=stores,
                catalogs=catalogs,
                now_factory=deps.now_factory,
            )
            _apply_intent(
                commands,
                kind=kind,
                intent=intent,
                fields=fields,
                actor=actor,
            )

        try:
            await asyncio.to_thread(_apply)
        except MasterDataCommandRejected as exc:
            _LOGGER.info("admin_coffee_equipment_reject", extra={"code": exc.code})
            return RedirectResponse(
                f"/admin{path}?error={quote(exc.code)}",
                status_code=303,
            )
        return RedirectResponse(f"/admin{path}", status_code=303)

    catalog_post.__name__ = f"coffee_equipment_{kind}_post"
    router.post(path)(catalog_post)


def _rows(catalogs: CoffeeEquipmentCatalogs, kind: str) -> tuple[_CatalogRow, ...]:
    if kind == "model":
        return tuple(
            _CatalogRow(model.model_id, model.name, model.floor_standing)
            for model in catalogs.models.list_all()
        )
    if kind == "stand_type":
        return tuple(
            _CatalogRow(item.stand_type_id, item.name, None)
            for item in catalogs.stand_types.list_all()
        )
    return tuple(
        _CatalogRow(item.stand_color_id, item.name, None)
        for item in catalogs.stand_colors.list_all()
    )


def _apply_intent(
    commands: CoffeeEquipmentCommands,
    *,
    kind: str,
    intent: str,
    fields: dict[str, str],
    actor: int,
) -> None:
    name = fields.get("name", "")
    entry_id = fields.get("entry_id", "")
    floor_standing = "floor_standing" in fields
    if kind == "model" and intent == "create":
        commands.create_model(
            name=name, floor_standing=floor_standing, actor_telegram_user_id=actor
        )
        return
    if kind == "model" and intent == "save":
        commands.save_model(
            model_id=entry_id,
            name=name,
            floor_standing=floor_standing,
            actor_telegram_user_id=actor,
        )
        return
    if kind == "model" and intent == "delete":
        commands.delete_model(model_id=entry_id, actor_telegram_user_id=actor)
        return
    if kind == "stand_type" and intent == "create":
        commands.create_stand_type(name=name, actor_telegram_user_id=actor)
        return
    if kind == "stand_type" and intent == "save":
        commands.save_stand_type(stand_type_id=entry_id, name=name, actor_telegram_user_id=actor)
        return
    if kind == "stand_type" and intent == "delete":
        commands.delete_stand_type(stand_type_id=entry_id, actor_telegram_user_id=actor)
        return
    if kind == "stand_color" and intent == "create":
        commands.create_stand_color(name=name, actor_telegram_user_id=actor)
        return
    if kind == "stand_color" and intent == "save":
        commands.save_stand_color(stand_color_id=entry_id, name=name, actor_telegram_user_id=actor)
        return
    if kind == "stand_color" and intent == "delete":
        commands.delete_stand_color(stand_color_id=entry_id, actor_telegram_user_id=actor)
        return
    raise MasterDataCommandRejected("unknown catalog intent", code="catalog_name_invalid")
