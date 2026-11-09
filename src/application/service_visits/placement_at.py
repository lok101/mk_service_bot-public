from __future__ import annotations

from datetime import datetime

from beartype import beartype

from src.application.service_visits.ports import PlacementAtSnapshot


@beartype
def resolve_placement_at(
    placements: tuple[PlacementAtSnapshot, ...],
    at: datetime,
) -> PlacementAtSnapshot | None:
    """Placement, покрывающий момент `at`; интервал полуоткрытый."""
    ordered = sorted(placements, key=lambda item: item.valid_from, reverse=True)
    for placement in ordered:
        if placement.valid_from > at:
            continue
        if placement.valid_to is not None and at >= placement.valid_to:
            continue
        return placement
    return None
