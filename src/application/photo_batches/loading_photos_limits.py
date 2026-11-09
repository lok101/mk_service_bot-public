from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

MICROMARKET_KIND = "micro_market"
COFFEE_KIND = "coffee"
MICROMARKET_LOADING_PHOTOS_LIMITS = (2, 2)


@runtime_checkable
class LoadingPhotosMachineKindLookup(Protocol):
    @beartype
    def kind_of(self, machine_code: str) -> str | None: ...


@beartype
@dataclass(frozen=True, slots=True)
class LoadingPhotosProfileCue:
    min_count: int
    max_count: int
    checklist_items: tuple[str, ...]


@runtime_checkable
class LoadingPhotosProfileLookup(Protocol):
    """Resolve coffee visit-photo profile cues; None = miss."""

    @beartype
    def cue_for(self, machine_code: str) -> LoadingPhotosProfileCue | None: ...


@beartype
def loading_photos_limits_for_kind(
    kind: str | None,
    coffee_min: int,
    coffee_max: int,
) -> tuple[int, int]:
    if kind == MICROMARKET_KIND:
        return MICROMARKET_LOADING_PHOTOS_LIMITS
    if kind not in (None, COFFEE_KIND):
        return (0, 0)
    return (coffee_min, coffee_max)


@beartype
def resolve_loading_photos_cues(
    *,
    machine_code: str,
    coffee_min: int,
    coffee_max: int,
    kind_lookup: object | None,
    profile_lookup: object | None,
    profile_strict: bool,
    coffee_checklist: tuple[str, ...],
) -> tuple[int, int, tuple[str, ...], bool, bool]:
    """Return (min, max, checklist, is_micromarket, profile_missing_strict).

    ``profile_missing_strict`` is True when the upload must be refused: coffee
    has no profile and strict mode is on, or the machine kind is neither coffee
    nor a micromarket. Callers must not show the coffee checklist for that kind.
    Lookups are ``object | None`` so Telegram tests can pass MagicMock deps
    (same pattern as ``resolve_loading_photos_ui_limits``).
    """
    kind: str | None = None
    if kind_lookup is not None:
        raw_kind = kind_lookup.kind_of(machine_code)  # type: ignore[attr-defined]
        kind = raw_kind if isinstance(raw_kind, str) else None
    if kind == MICROMARKET_KIND:
        return (
            MICROMARKET_LOADING_PHOTOS_LIMITS[0],
            MICROMARKET_LOADING_PHOTOS_LIMITS[1],
            (
                "1. Общий план ДО.",
                "2. Общий план ПОСЛЕ.",
            ),
            True,
            False,
        )
    if kind not in (None, COFFEE_KIND):
        return (0, 0, (), False, True)
    if profile_lookup is not None:
        cue = profile_lookup.cue_for(machine_code)  # type: ignore[attr-defined]
        if isinstance(cue, LoadingPhotosProfileCue):
            return (
                cue.min_count,
                cue.max_count,
                cue.checklist_items,
                False,
                False,
            )
        if cue is None and profile_strict:
            return (0, 0, (), False, True)
    min_count, max_count = loading_photos_limits_for_kind(
        kind,
        coffee_min,
        coffee_max,
    )
    return (min_count, max_count, coffee_checklist, False, False)
