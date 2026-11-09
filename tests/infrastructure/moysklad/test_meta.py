from __future__ import annotations

from uuid import UUID

from src.infrastructure.integrations.moysklad.meta import entity_meta, wrap_entity_meta


def test_entity_meta_for_store_matches_api_shape() -> None:
    store_id = UUID("11111111-1111-1111-1111-111111111111")
    meta = entity_meta(store_id, "store")
    assert meta == {
        "href": "https://api.moysklad.ru/api/remap/1.2/entity/store/11111111-1111-1111-1111-111111111111",
        "metadataHref": "https://api.moysklad.ru/api/remap/1.2/entity/store/metadata",
        "type": "store",
        "mediaType": "application/json",
    }


def test_wrap_entity_meta() -> None:
    store_id = UUID("11111111-1111-1111-1111-111111111111")
    assert wrap_entity_meta(store_id, "organization") == {
        "meta": entity_meta(store_id, "organization")
    }
