from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.infrastructure.integrations.moysklad.quantities import MoySkladLinePosition
from src.infrastructure.integrations.moysklad.stock_document_registrar import post_stock_document

ORG = uuid4()
PROJECT = uuid4()
CHANNEL = uuid4()
AGENT = uuid4()
STORE = uuid4()


def test_post_stock_document_includes_project_and_sales_channel() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    asyncio.run(
        post_stock_document(
            client=client,
            organization_id=ORG,
            entity_path="demand",
            warehouse_code="M1",
            positions=[MoySkladLinePosition(product_code="P1", quantity=1)],
            moment=datetime(2026, 8, 9, 23, 55, tzinfo=UTC),
            external_code="mk-service-bot:daily-sales-demand:M1:2026-08-09",
            agent_id=AGENT,
            project_id=PROJECT,
            sales_channel_id=CHANNEL,
        ),
    )
    body = client.posted_payloads[-1]
    assert "project" in body
    assert "salesChannel" in body
    assert "agent" in body


def test_post_stock_document_position_price_kop() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    asyncio.run(
        post_stock_document(
            client=client,
            organization_id=ORG,
            entity_path="demand",
            warehouse_code="M1",
            positions=[MoySkladLinePosition(product_code="P1", quantity=2, price=12500)],
            moment=datetime(2026, 8, 9, 23, 55, tzinfo=UTC),
            external_code="x",
        ),
    )
    rows = client.posted_payloads[-1]["positions"]["rows"]  # type: ignore[index]
    assert rows[0]["price"] == 12500


def test_post_stock_document_omits_optional_when_none() -> None:
    client = FakeMoySkladClient(store_ids_by_code={"M1": STORE})
    asyncio.run(
        post_stock_document(
            client=client,
            organization_id=ORG,
            entity_path="demand",
            warehouse_code="M1",
            positions=[MoySkladLinePosition(product_code="P1", quantity=1)],
            moment=datetime(2026, 8, 9, 23, 55, tzinfo=UTC),
            external_code="x",
        ),
    )
    body = client.posted_payloads[-1]
    assert "project" not in body
    assert "salesChannel" not in body
