from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.infrastructure.integrations.moysklad.quantities import MoySkladLinePosition
from src.infrastructure.integrations.moysklad.stock_document_registrar import post_stock_document

_ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000001")
_AGENT_ID = UUID("00000000-0000-0000-0000-000000000010")
_MOMENT = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)


def test_post_stock_document_includes_agent_when_agent_id_set() -> None:
    client = FakeMoySkladClient()
    positions = [
        MoySkladLinePosition(
            product_code="coffee-1",
            quantity=1,
        ),
    ]

    asyncio.run(
        post_stock_document(
            client=client,
            organization_id=_ORGANIZATION_ID,
            entity_path="demand",
            warehouse_code="vm-01",
            positions=positions,
            moment=_MOMENT,
            external_code="mk-service-bot:test:demand",
            agent_id=_AGENT_ID,
        ),
    )

    assert len(client.posted_payloads) == 1
    agent = client.posted_payloads[0]["agent"]
    assert isinstance(agent, dict)
    meta = agent["meta"]
    assert isinstance(meta, dict)
    assert meta["type"] == "counterparty"
    assert meta["href"].endswith(f"/counterparty/{_AGENT_ID}")


def test_post_stock_document_omits_agent_when_agent_id_none() -> None:
    client = FakeMoySkladClient()
    positions = [
        MoySkladLinePosition(
            product_code="coffee-1",
            quantity=1,
        ),
    ]

    asyncio.run(
        post_stock_document(
            client=client,
            organization_id=_ORGANIZATION_ID,
            entity_path="loss",
            warehouse_code="vm-01",
            positions=positions,
            moment=_MOMENT,
            external_code="mk-service-bot:test:loss",
        ),
    )

    assert "agent" not in client.posted_payloads[0]
