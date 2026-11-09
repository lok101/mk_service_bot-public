from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import EventId
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.infrastructure.outbox.serialization import (
    event_from_outbox_document,
    event_to_outbox_document,
)


def test_micromarket_shop_list_publish_event_roundtrip() -> None:
    event = MicromarketShopListPublishRequested(
        event_id=EventId("pub-1"),
        machine_code="701",
        publication_id="pub-1",
        lines=(("2311", "10", 6348, False),),
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
    )
    document = event_to_outbox_document(event)
    assert document["aggregate_type"] == "MicromarketShopList"
    restored = event_from_outbox_document(document)
    assert restored == event
