from __future__ import annotations

from src.application.photo_batches.loading_photos_limits import (
    loading_photos_limits_for_kind,
)


def test_loading_photos_limits_for_kind_micromarket_is_exact_two() -> None:
    assert loading_photos_limits_for_kind("micro_market", coffee_min=2, coffee_max=10) == (2, 2)


def test_loading_photos_limits_for_kind_coffee_passthrough_env() -> None:
    assert loading_photos_limits_for_kind("coffee", coffee_min=3, coffee_max=8) == (3, 8)


def test_loading_photos_limits_for_kind_unknown_or_none_uses_coffee_env() -> None:
    assert loading_photos_limits_for_kind(None, coffee_min=2, coffee_max=10) == (2, 10)


def test_loading_photos_limits_for_kind_snack_is_not_coffee() -> None:
    assert loading_photos_limits_for_kind("snack", coffee_min=2, coffee_max=10) == (0, 0)
