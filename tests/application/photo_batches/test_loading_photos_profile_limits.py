from __future__ import annotations

from src.application.photo_batches.loading_photos_limits import (
    LoadingPhotosProfileCue,
    resolve_loading_photos_cues,
)

_COFFEE = (
    "1. Общий план ДО.",
    "2. Органайзер.",
)


class _Kind:
    def __init__(self, kind: str | None) -> None:
        self._kind = kind

    def kind_of(self, machine_code: str) -> str | None:
        return self._kind


class _Profile:
    def __init__(self, cue: LoadingPhotosProfileCue | None) -> None:
        self._cue = cue

    def cue_for(self, machine_code: str) -> LoadingPhotosProfileCue | None:
        return self._cue


def test_bot_cue_uses_content_group_titles() -> None:
    """Bot checklist titles come from profile content groups (min=max=N)."""
    cue = LoadingPhotosProfileCue(
        min_count=2,
        max_count=2,
        checklist_items=("До обслуживания", "После обслуживания"),
    )
    min_c, max_c, items, is_mm, missing = resolve_loading_photos_cues(
        machine_code="M1",
        coffee_min=2,
        coffee_max=10,
        kind_lookup=_Kind("coffee"),
        profile_lookup=_Profile(cue),
        profile_strict=False,
        coffee_checklist=_COFFEE,
    )
    assert missing is False
    assert is_mm is False
    assert (min_c, max_c) == (2, 2)
    assert items == ("До обслуживания", "После обслуживания")


def test_micromarket_limits_unchanged() -> None:
    test_micromarket_ignores_profile()


def test_strict_profile_miss_unchanged() -> None:
    test_strict_miss_flags_missing()


def test_profile_cue_overrides_coffee_env() -> None:
    cue = LoadingPhotosProfileCue(
        min_count=3,
        max_count=3,
        checklist_items=("1. A", "2. B", "3. C"),
    )
    min_c, max_c, items, is_mm, missing = resolve_loading_photos_cues(
        machine_code="M1",
        coffee_min=2,
        coffee_max=10,
        kind_lookup=_Kind("coffee"),
        profile_lookup=_Profile(cue),
        profile_strict=False,
        coffee_checklist=_COFFEE,
    )
    assert (min_c, max_c) == (3, 3)
    assert items == cue.checklist_items
    assert is_mm is False
    assert missing is False


def test_micromarket_ignores_profile() -> None:
    cue = LoadingPhotosProfileCue(min_count=9, max_count=9, checklist_items=("x",) * 9)
    min_c, max_c, items, is_mm, missing = resolve_loading_photos_cues(
        machine_code="M1",
        coffee_min=2,
        coffee_max=10,
        kind_lookup=_Kind("micro_market"),
        profile_lookup=_Profile(cue),
        profile_strict=True,
        coffee_checklist=_COFFEE,
    )
    assert (min_c, max_c) == (2, 2)
    assert is_mm is True
    assert missing is False
    assert "Органайзер" not in "\n".join(items)


def test_strict_miss_flags_missing() -> None:
    min_c, max_c, items, is_mm, missing = resolve_loading_photos_cues(
        machine_code="M1",
        coffee_min=2,
        coffee_max=10,
        kind_lookup=_Kind("coffee"),
        profile_lookup=_Profile(None),
        profile_strict=True,
        coffee_checklist=_COFFEE,
    )
    assert missing is True
    assert (min_c, max_c) == (0, 0)
    assert items == ()
    assert is_mm is False


def test_snack_does_not_receive_coffee_checklist() -> None:
    cue = LoadingPhotosProfileCue(
        min_count=10,
        max_count=10,
        checklist_items=_COFFEE,
    )
    min_c, max_c, items, is_mm, missing = resolve_loading_photos_cues(
        machine_code="S1",
        coffee_min=2,
        coffee_max=10,
        kind_lookup=_Kind("snack"),
        profile_lookup=_Profile(cue),
        profile_strict=False,
        coffee_checklist=_COFFEE,
    )
    assert missing is True
    assert (min_c, max_c) == (0, 0)
    assert items == ()
    assert is_mm is False
    assert "Органайзер" not in "\n".join(items)


def test_non_strict_miss_falls_back_to_env() -> None:
    min_c, max_c, items, is_mm, missing = resolve_loading_photos_cues(
        machine_code="M1",
        coffee_min=2,
        coffee_max=10,
        kind_lookup=_Kind("coffee"),
        profile_lookup=_Profile(None),
        profile_strict=False,
        coffee_checklist=_COFFEE,
    )
    assert missing is False
    assert (min_c, max_c) == (2, 10)
    assert items == _COFFEE
