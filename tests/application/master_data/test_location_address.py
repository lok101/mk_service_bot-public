from __future__ import annotations

from src.application.master_data.location_address import (
    compose_location_display_name,
    effective_location_display_name,
    location_address_parts_complete,
)


def test_compose_location_display_name_formula() -> None:
    assert (
        compose_location_display_name(name="МЦ Здоровая семья", street="Фучика", house="3")
        == "МЦ Здоровая семья | Фучика, 3"
    )


def test_location_address_parts_complete_requires_all() -> None:
    assert location_address_parts_complete(name="A", city="Казань", street="Фучика", house="3")
    assert not location_address_parts_complete(name="A", city="  ", street="Фучика", house="3")
    assert not location_address_parts_complete(name="", city="Казань", street="Фучика", house="3")


def test_effective_location_display_name_legacy_fallback() -> None:
    assert (
        effective_location_display_name(
            name="",
            city="",
            street="",
            house="",
            display_name="МЦ Здоровая семья | Фучика, 3",
        )
        == "МЦ Здоровая семья | Фучика, 3"
    )
    assert (
        effective_location_display_name(
            name="МЦ",
            city="Казань",
            street="Фучика",
            house="3",
            display_name="ignored",
        )
        == "МЦ | Фучика, 3"
    )
