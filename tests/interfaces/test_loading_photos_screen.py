from __future__ import annotations

from src.interfaces.telegram.dialog_layout import TELEGRAM_DIALOG_MIN_WIDTH_LINE
from src.interfaces.telegram.machines.loading_photos_screen import (
    build_loading_photos_screen_text,
    insufficient_photos_alert,
    max_photos_alert,
    resolve_loading_photos_ui_limits,
)


class _CoffeeKind:
    def kind_of(self, machine_code: str) -> str | None:
        return "coffee"


def test_resolve_loading_photos_ui_limits_tuple_order() -> None:
    min_count, max_count, is_micromarket, checklist, missing = resolve_loading_photos_ui_limits(
        machine_code="501",
        coffee_min=8,
        coffee_max=10,
        kind_lookup=_CoffeeKind(),
        profile_lookup=None,
    )
    assert (min_count, max_count) == (8, 10)
    assert is_micromarket is False
    assert isinstance(checklist, tuple)
    assert "2. Органайзер." in checklist
    assert missing is False


def test_resolve_loading_photos_ui_limits_kind_lookup_none_no_beartype() -> None:
    min_count, max_count, is_micromarket, checklist, missing = resolve_loading_photos_ui_limits(
        machine_code="501",
        coffee_min=8,
        coffee_max=10,
        kind_lookup=None,
        profile_lookup=None,
    )
    assert (min_count, max_count) == (8, 10)
    assert is_micromarket is False
    assert isinstance(checklist, tuple)
    assert missing is False


def test_loading_photos_screen_starts_with_min_width_line() -> None:
    text = build_loading_photos_screen_text(
        photo_count=0,
        min_count=2,
        max_count=10,
        preview_index=0,
    )
    assert text.splitlines()[0] == TELEGRAM_DIALOG_MIN_WIDTH_LINE


def test_loading_photos_screen_lists_required_shots() -> None:
    text = build_loading_photos_screen_text(
        photo_count=0,
        min_count=2,
        max_count=10,
        preview_index=0,
    )
    assert "1. Общий план ДО." in text
    assert "9. График визитов." in text
    assert "10. Общий план ПОСЛЕ." in text


def test_loading_photos_screen_micromarket_two_item_checklist() -> None:
    # happy: MM checklist is only ДО / ПОСЛЕ with 2/2 counter
    text = build_loading_photos_screen_text(
        photo_count=0,
        min_count=2,
        max_count=2,
        preview_index=0,
        is_micromarket=True,
    )
    assert "1. Общий план ДО." in text
    assert "2. Общий план ПОСЛЕ." in text
    assert "Загружено: 0 (мин. 2, макс. 2)" in text
    assert "Органайзер." not in text
    assert "3." not in text
    assert "10." not in text


def test_loading_photos_screen_text_shows_min_and_max() -> None:
    text = build_loading_photos_screen_text(
        photo_count=3,
        min_count=2,
        max_count=10,
        preview_index=0,
    )
    assert "Загружено: 3 (мин. 2, макс. 10)" in text
    assert "Просмотр: фото 1 из 3" in text


def test_loading_photos_screen_text_shows_limit_reached() -> None:
    text = build_loading_photos_screen_text(
        photo_count=10,
        min_count=2,
        max_count=10,
        preview_index=0,
    )
    assert "Достигнут лимит фотографий." in text


def test_loading_photos_screen_text_without_photos() -> None:
    text = build_loading_photos_screen_text(
        photo_count=0,
        min_count=2,
        max_count=10,
        preview_index=0,
    )
    assert "Загружено: 0 (мин. 2, макс. 10)" in text
    assert "Просмотр" not in text


def test_insufficient_photos_alert() -> None:
    assert insufficient_photos_alert(2) == "Нужно минимум 2 фотографий."


def test_max_photos_alert() -> None:
    assert max_photos_alert(10) == "Максимум 10 фотографий."
