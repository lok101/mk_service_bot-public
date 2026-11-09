from __future__ import annotations

from datetime import UTC, datetime

from src.application.service_visits.placement_at import resolve_placement_at
from src.application.service_visits.ports import PlacementAtSnapshot
from src.domain.ids import MachineId

_MACHINE = MachineId("101")
_BOUNDARY = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)


def test_placement_at_open_interval() -> None:
    placements = (
        PlacementAtSnapshot(
            machine_id=_MACHINE,
            location_id="1",
            valid_from=datetime(2026, 7, 1, tzinfo=UTC),
            valid_to=None,
        ),
    )

    before_start = resolve_placement_at(placements, datetime(2026, 6, 30, tzinfo=UTC))
    inside = resolve_placement_at(placements, datetime(2026, 8, 20, tzinfo=UTC))

    assert before_start is None
    assert inside is not None
    assert inside.location_id == "1"


def test_placement_at_mid_relocation() -> None:
    placements = (
        PlacementAtSnapshot(
            machine_id=_MACHINE,
            location_id="1",
            valid_from=datetime(2026, 7, 1, tzinfo=UTC),
            valid_to=_BOUNDARY,
        ),
        PlacementAtSnapshot(
            machine_id=_MACHINE,
            location_id="2",
            valid_from=_BOUNDARY,
            valid_to=None,
        ),
    )

    before = resolve_placement_at(placements, datetime(2026, 8, 14, 12, 0, tzinfo=UTC))
    at_boundary = resolve_placement_at(placements, _BOUNDARY)
    after = resolve_placement_at(placements, datetime(2026, 8, 16, 12, 0, tzinfo=UTC))

    assert before is not None
    assert before.location_id == "1"
    assert at_boundary is not None
    assert at_boundary.location_id == "2"
    assert after is not None
    assert after.location_id == "2"
