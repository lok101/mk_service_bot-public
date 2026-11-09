from __future__ import annotations

from src.application.master_data import MasterLocation


def test_master_location_roundtrip_serialization() -> None:
    loc = MasterLocation(
        location_id="loc-1",
        name="Школа",
        city="Екб",
        street="Ленина",
        house="1",
        display_name="Екб, Ленина, 1",
        latitude=None,
        longitude=None,
    )
    assert loc.location_id == "loc-1"
    assert loc.name == "Школа"
    assert loc.display_name == "Екб, Ленина, 1"
