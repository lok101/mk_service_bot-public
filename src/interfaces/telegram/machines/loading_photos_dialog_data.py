from __future__ import annotations

import uuid
from typing import Any

from aiogram_dialog import DialogManager

from src.domain.ids import BatchId
from src.domain.photo_batch import PhotoRef

_BATCH_ID_KEY = "loading_photos_batch_id"
_DRAFT_KEY = "loading_photos_draft"
_INDEX_KEY = "loading_photos_index"


def init_loading_photos_session(manager: DialogManager) -> None:
    manager.dialog_data[_BATCH_ID_KEY] = BatchId(str(uuid.uuid4())).value
    manager.dialog_data[_DRAFT_KEY] = []
    manager.dialog_data[_INDEX_KEY] = 0


def clear_loading_photos_session(manager: DialogManager) -> None:
    manager.dialog_data.pop(_BATCH_ID_KEY, None)
    manager.dialog_data.pop(_DRAFT_KEY, None)
    manager.dialog_data.pop(_INDEX_KEY, None)


def get_loading_photos_batch_id(manager: DialogManager) -> BatchId:
    batch_id = manager.dialog_data.get(_BATCH_ID_KEY)
    if not isinstance(batch_id, str) or not batch_id:
        raise ValueError("Loading photos batch id is missing")
    return BatchId(batch_id)


def _read_draft(manager: DialogManager) -> list[dict[str, Any]]:
    draft = manager.dialog_data.get(_DRAFT_KEY)
    if not isinstance(draft, list):
        return []
    return draft


def photo_count(manager: DialogManager) -> int:
    return len(_read_draft(manager))


def get_photo_index(manager: DialogManager) -> int:
    index = manager.dialog_data.get(_INDEX_KEY)
    if not isinstance(index, int):
        return 0
    return index


def set_photo_index(manager: DialogManager, index: int) -> None:
    manager.dialog_data[_INDEX_KEY] = index


def append_photo(
    manager: DialogManager,
    *,
    file_id: str,
    file_unique_id: str,
    message_id: int,
    media_group_id: str | None = None,
) -> None:
    draft = list(_read_draft(manager))
    draft.append(
        {
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "message_id": message_id,
            "media_group_id": media_group_id,
        },
    )
    manager.dialog_data[_DRAFT_KEY] = draft
    manager.dialog_data[_INDEX_KEY] = len(draft) - 1


def try_append_photo(
    manager: DialogManager,
    *,
    max_count: int,
    file_id: str,
    file_unique_id: str,
    message_id: int,
    media_group_id: str | None = None,
) -> bool:
    draft = list(_read_draft(manager))
    if any(item.get("file_unique_id") == file_unique_id for item in draft):
        return True
    if len(draft) >= max_count:
        return False
    draft.append(
        {
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "message_id": message_id,
            "media_group_id": media_group_id,
        },
    )
    manager.dialog_data[_DRAFT_KEY] = draft
    manager.dialog_data[_INDEX_KEY] = len(draft) - 1
    return True


def photos_as_refs(manager: DialogManager) -> tuple[PhotoRef, ...]:
    refs: list[PhotoRef] = []
    for item in _read_draft(manager):
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        file_unique_id = item.get("file_unique_id")
        message_id = item.get("message_id")
        if (
            not isinstance(file_id, str)
            or not isinstance(file_unique_id, str)
            or not isinstance(message_id, int)
        ):
            continue
        media_group_id = item.get("media_group_id")
        refs.append(
            PhotoRef(
                file_id=file_id,
                file_unique_id=file_unique_id,
                message_id=message_id,
                media_group_id=media_group_id if isinstance(media_group_id, str) else None,
            ),
        )
    return tuple(refs)


def current_photo_draft(manager: DialogManager) -> dict[str, Any] | None:
    draft = _read_draft(manager)
    if not draft:
        return None
    index = get_photo_index(manager)
    if index < 0 or index >= len(draft):
        index = 0
    item = draft[index]
    if not isinstance(item, dict):
        return None
    return item
