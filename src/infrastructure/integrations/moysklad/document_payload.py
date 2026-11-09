from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from beartype import beartype

from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.integrations.moysklad.meta import wrap_entity_meta
from src.infrastructure.integrations.moysklad.quantities import MoySkladLinePosition


@beartype
def organization_meta(organization_id: UUID) -> Mapping[str, object]:
    return wrap_entity_meta(organization_id, "organization")


@beartype
def project_meta(project_id: UUID) -> Mapping[str, object]:
    return wrap_entity_meta(project_id, "project")


@beartype
def store_meta(store_id: UUID) -> Mapping[str, object]:
    return wrap_entity_meta(store_id, "store")


@beartype
async def assortment_position_rows(
    client: MoySkladClientPort,
    positions: list[MoySkladLinePosition],
) -> list[dict[str, object]]:
    if not positions:
        return []

    assortments = await client.resolve_assortments_by_codes(
        [position.product_code for position in positions],
    )
    rows: list[dict[str, object]] = []
    for position in positions:
        row: dict[str, object] = {
            "quantity": position.quantity,
            "assortment": wrap_entity_meta(
                assortments[position.product_code].id,
                assortments[position.product_code].entity_type,
            ),
        }
        if position.price is not None:
            row["price"] = position.price
        rows.append(row)
    return rows
