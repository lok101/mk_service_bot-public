from __future__ import annotations

from src.interfaces.telegram.dialog_layout import (
    TELEGRAM_DIALOG_MIN_WIDTH_CHAR_COUNT,
    TELEGRAM_DIALOG_MIN_WIDTH_LINE,
)


def test_telegram_dialog_min_width_line_length() -> None:
    assert len(TELEGRAM_DIALOG_MIN_WIDTH_LINE) == TELEGRAM_DIALOG_MIN_WIDTH_CHAR_COUNT


def test_telegram_dialog_min_width_line_is_dots() -> None:
    assert TELEGRAM_DIALOG_MIN_WIDTH_LINE == "." * TELEGRAM_DIALOG_MIN_WIDTH_CHAR_COUNT
