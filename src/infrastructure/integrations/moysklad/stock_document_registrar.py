from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from beartype import beartype

from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.integrations.moysklad.constants import CREATED_AUTOMATICALLY
from src.infrastructure.integrations.moysklad.document_payload import (
    assortment_position_rows,
    organization_meta,
    project_meta,
    store_meta,
)
from src.infrastructure.integrations.moysklad.meta import wrap_entity_meta
from src.infrastructure.integrations.moysklad.quantities import MoySkladLinePosition
from src.infrastructure.integrations.moysklad.timezone import format_moment


@beartype
async def post_stock_document(
    *,
    client: MoySkladClientPort,
    organization_id: UUID,
    entity_path: str,
    warehouse_code: str,
    positions: list[MoySkladLinePosition],
    moment: datetime,
    external_code: str,
    agent_id: UUID | None = None,
    project_id: UUID | None = None,
    sales_channel_id: UUID | None = None,
) -> Mapping[str, Any]:
    warehouse_id = await client.get_store_id_by_code(warehouse_code)
    position_rows = await assortment_position_rows(client, positions)

    data: dict[str, object] = {
        "externalCode": external_code,
        "moment": format_moment(moment),
        "description": CREATED_AUTOMATICALLY,
        "organization": organization_meta(organization_id),
        "store": store_meta(warehouse_id),
        "positions": {"rows": position_rows},
    }

    if agent_id is not None:
        data["agent"] = wrap_entity_meta(agent_id, "counterparty")
    if project_id is not None:
        data["project"] = project_meta(project_id)
    if sales_channel_id is not None:
        data["salesChannel"] = wrap_entity_meta(sales_channel_id, "saleschannel")

    return await client.post_entity(entity_path=entity_path, body=data)
