from __future__ import annotations

from uuid import UUID

from beartype import beartype

from src.infrastructure.integrations.moysklad.constants import MOYSKLAD_ENTITY_BASE_URL


@beartype
def entity_meta(entity_id: UUID, entity_type: str) -> dict[str, str]:
    return {
        "href": f"{MOYSKLAD_ENTITY_BASE_URL}/{entity_type}/{entity_id}",
        "metadataHref": f"{MOYSKLAD_ENTITY_BASE_URL}/{entity_type}/metadata",
        "type": entity_type,
        "mediaType": "application/json",
    }


@beartype
def wrap_entity_meta(entity_id: UUID, entity_type: str) -> dict[str, dict[str, str]]:
    return {"meta": entity_meta(entity_id, entity_type)}
