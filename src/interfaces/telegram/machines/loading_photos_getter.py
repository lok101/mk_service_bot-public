from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram.enums import ContentType
from aiogram_dialog import DialogManager
from aiogram_dialog.api.entities.media import MediaAttachment, MediaId

from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.dialog_data import get_selected_machine_id
from src.interfaces.telegram.machines.loading_photos_dialog_data import (
    current_photo_draft,
    get_photo_index,
    photo_count,
)
from src.interfaces.telegram.machines.loading_photos_screen import (
    build_loading_photos_screen_text,
    resolve_loading_photos_ui_limits,
)

DialogDataGetter = Callable[..., Awaitable[dict[str, object]]]


def build_loading_photos_getter(deps: MachineListDeps) -> DialogDataGetter:
    async def get_loading_photos(
        dialog_manager: DialogManager,
        **kwargs: object,
    ) -> dict[str, object]:
        count = photo_count(dialog_manager)
        machine_id = get_selected_machine_id(dialog_manager)
        profile_lookup = getattr(deps, "loading_photos_profile_lookup", None)
        profile_strict = bool(getattr(deps, "visit_photo_profile_strict", False))
        (
            min_count,
            max_count,
            is_micromarket,
            checklist,
            profile_missing_strict,
        ) = resolve_loading_photos_ui_limits(
            machine_code=machine_id.value,
            coffee_min=deps.loading_photos_min_count,
            coffee_max=deps.loading_photos_max_count,
            kind_lookup=deps.machine_kind_lookup,
            profile_lookup=profile_lookup,
            profile_strict=profile_strict,
        )
        index = get_photo_index(dialog_manager)
        if count > 0 and index >= count:
            index = count - 1

        can_send = not profile_missing_strict and min_count <= count <= max_count
        payload: dict[str, object] = {
            "loading_photos_screen_text": build_loading_photos_screen_text(
                photo_count=count,
                min_count=min_count,
                max_count=max_count,
                preview_index=index if count > 0 else 0,
                checklist=checklist,
                is_micromarket=is_micromarket,
                profile_missing_strict=profile_missing_strict,
            ),
            "photo_count": count,
            "loading_photos_min_count": min_count,
            "loading_photos_max_count": max_count,
            "can_send_photos": can_send,
            "has_photos": count > 0,
            "show_photo_pagination": count > 1,
        }

        current = current_photo_draft(dialog_manager)
        if current is not None:
            file_id = current.get("file_id")
            file_unique_id = current.get("file_unique_id")
            if isinstance(file_id, str) and isinstance(file_unique_id, str):
                payload["media"] = MediaAttachment(
                    type=ContentType.PHOTO,
                    file_id=MediaId(file_id, file_unique_id),
                )

        return payload

    return get_loading_photos
