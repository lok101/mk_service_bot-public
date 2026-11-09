from __future__ import annotations

from beartype import beartype


@beartype
def compose_location_display_name(*, name: str, street: str, house: str) -> str:
    return f"{name} | {street}, {house}"


@beartype
def location_address_parts_complete(
    *,
    name: str,
    city: str,
    street: str,
    house: str,
) -> bool:
    return all(part.strip() for part in (name, city, street, house))


@beartype
def effective_location_display_name(
    *,
    name: str,
    city: str,
    street: str,
    house: str,
    display_name: str,
) -> str:
    if location_address_parts_complete(name=name, city=city, street=street, house=house):
        return compose_location_display_name(name=name, street=street, house=house)
    return display_name
