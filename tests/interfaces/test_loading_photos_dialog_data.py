from __future__ import annotations

from unittest.mock import MagicMock

from src.interfaces.telegram.machines.loading_photos_dialog_data import (
    append_photo,
    clear_loading_photos_session,
    get_loading_photos_batch_id,
    init_loading_photos_session,
    photo_count,
    photos_as_refs,
    try_append_photo,
)


def test_init_and_clear_loading_photos_session() -> None:
    manager = MagicMock()
    manager.dialog_data = {}

    init_loading_photos_session(manager)
    assert "loading_photos_batch_id" in manager.dialog_data
    assert manager.dialog_data["loading_photos_draft"] == []
    assert manager.dialog_data["loading_photos_index"] == 0

    batch_id = get_loading_photos_batch_id(manager)
    assert batch_id.value

    clear_loading_photos_session(manager)
    assert "loading_photos_batch_id" not in manager.dialog_data


def test_append_photo_builds_refs() -> None:
    manager = MagicMock()
    manager.dialog_data = {}
    init_loading_photos_session(manager)

    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=100,
    )
    append_photo(
        manager,
        file_id="file-2",
        file_unique_id="unique-2",
        message_id=101,
        media_group_id="group-1",
    )

    assert photo_count(manager) == 2
    refs = photos_as_refs(manager)
    assert len(refs) == 2
    assert refs[0].file_id == "file-1"
    assert refs[1].media_group_id == "group-1"


def test_try_append_photo_rejects_at_max() -> None:
    manager = MagicMock()
    manager.dialog_data = {}
    init_loading_photos_session(manager)

    for index in range(10):
        assert try_append_photo(
            manager,
            max_count=10,
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )

    assert photo_count(manager) == 10
    assert not try_append_photo(
        manager,
        max_count=10,
        file_id="file-extra",
        file_unique_id="unique-extra",
        message_id=99,
    )
    assert photo_count(manager) == 10


def test_try_append_photo_is_idempotent_for_duplicate_unique_id() -> None:
    manager = MagicMock()
    manager.dialog_data = {}
    init_loading_photos_session(manager)

    assert try_append_photo(
        manager,
        max_count=10,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )
    assert try_append_photo(
        manager,
        max_count=10,
        file_id="file-1-copy",
        file_unique_id="unique-1",
        message_id=2,
    )

    assert photo_count(manager) == 1
