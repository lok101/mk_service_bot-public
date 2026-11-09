from __future__ import annotations

from collections.abc import Callable

from beartype import beartype


@beartype
def snapshot_for_event[T](
    *,
    event_id: str,
    primary_lookup: Callable[[str], T | None],
    fallback_lookup: Callable[[], T | None],
    not_found_error: Callable[[str], Exception],
) -> T:
    snapshot = primary_lookup(event_id)
    if snapshot is not None:
        return snapshot
    snapshot = fallback_lookup()
    if snapshot is not None:
        return snapshot
    raise not_found_error(event_id)
