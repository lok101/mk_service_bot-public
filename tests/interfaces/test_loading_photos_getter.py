from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from src.interfaces.telegram.machines.loading_photos_dialog_data import (
    append_photo,
    init_loading_photos_session,
)
from src.interfaces.telegram.machines.loading_photos_getter import (
    build_loading_photos_getter,
)


def _deps_mock(*, kind: str | None = None) -> MagicMock:
    deps = MagicMock()
    deps.loading_photos_min_count = 2
    deps.loading_photos_max_count = 10
    deps.loading_photos_profile_lookup = None
    deps.visit_photo_profile_strict = False
    if kind is None:
        deps.machine_kind_lookup = None
    else:
        deps.machine_kind_lookup = MagicMock()
        deps.machine_kind_lookup.kind_of.return_value = kind
    return deps


async def _test_loading_photos_getter_can_send_when_minimum_reached() -> None:
    deps = _deps_mock()
    getter = build_loading_photos_getter(deps)

    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )

    payload_before = await getter(manager)
    assert payload_before["can_send_photos"] is False
    assert payload_before["photo_count"] == 1

    append_photo(
        manager,
        file_id="file-2",
        file_unique_id="unique-2",
        message_id=2,
    )
    payload_after = await getter(manager)
    assert payload_after["can_send_photos"] is True
    assert payload_after["photo_count"] == 2
    assert payload_after["has_photos"] is True
    assert "media" in payload_after


def test_loading_photos_getter_can_send_when_minimum_reached() -> None:
    asyncio.run(_test_loading_photos_getter_can_send_when_minimum_reached())


async def _test_loading_photos_getter_includes_max_count_in_screen_text() -> None:
    deps = _deps_mock()
    getter = build_loading_photos_getter(deps)

    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    for index in range(10):
        append_photo(
            manager,
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )

    payload = await getter(manager)

    assert payload["loading_photos_max_count"] == 10
    assert "макс. 10" in str(payload["loading_photos_screen_text"])
    assert "Достигнут лимит фотографий." in str(payload["loading_photos_screen_text"])


def test_loading_photos_getter_includes_max_count_in_screen_text() -> None:
    asyncio.run(_test_loading_photos_getter_includes_max_count_in_screen_text())


async def _test_loading_photos_getter_disables_send_when_over_max() -> None:
    deps = _deps_mock()
    getter = build_loading_photos_getter(deps)

    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    for index in range(11):
        append_photo(
            manager,
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )

    payload = await getter(manager)

    assert payload["photo_count"] == 11
    assert payload["can_send_photos"] is False


def test_loading_photos_getter_disables_send_when_over_max() -> None:
    asyncio.run(_test_loading_photos_getter_disables_send_when_over_max())


async def _test_loading_photos_getter_micromarket_uses_two_limits_and_checklist() -> None:
    # happy: kind micro_market → 2/2 + short checklist via helper
    deps = _deps_mock(kind="micro_market")
    getter = build_loading_photos_getter(deps)

    manager = MagicMock()
    manager.dialog_data = {"machine_id": "701"}
    init_loading_photos_session(manager)

    payload = await getter(manager)

    assert payload["loading_photos_min_count"] == 2
    assert payload["loading_photos_max_count"] == 2
    text = str(payload["loading_photos_screen_text"])
    assert "1. Общий план ДО." in text
    assert "2. Общий план ПОСЛЕ." in text
    assert "Органайзер." not in text
    assert "мин. 2, макс. 2" in text


def test_loading_photos_getter_micromarket_uses_two_limits_and_checklist() -> None:
    asyncio.run(_test_loading_photos_getter_micromarket_uses_two_limits_and_checklist())


async def _test_loading_photos_send_stub_micromarket_insufficient_under_two() -> None:
    # error covered in handlers file; getter can_send stays False under 2
    deps = _deps_mock(kind="micro_market")
    getter = build_loading_photos_getter(deps)

    manager = MagicMock()
    manager.dialog_data = {"machine_id": "701"}
    init_loading_photos_session(manager)
    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )

    payload = await getter(manager)
    assert payload["can_send_photos"] is False
    assert payload["photo_count"] == 1


def test_loading_photos_getter_micromarket_insufficient_under_two() -> None:
    asyncio.run(_test_loading_photos_send_stub_micromarket_insufficient_under_two())
