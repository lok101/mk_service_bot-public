from __future__ import annotations

from src.application.shared.product_title import product_name_for_lookup


def test_strips_icon_prefix_before_pipe() -> None:
    assert product_name_for_lookup("🟧 | Концентрат") == "Концентрат"


def test_returns_name_without_pipe_stripped() -> None:
    assert product_name_for_lookup("  Кофе  ") == "Кофе"
