from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pymongo.database import Database
from tests.integration.settlement_pipeline_helpers import (
    drain_handler_sync,
    post_warehouse_inventory,
)
from tests.integration.stack import build_warehouse_settlement_stack

from src.application.outbox.handler_ids import (
    TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
)
from src.domain.product_catalog import ProductUnit
from src.infrastructure.testing import TEST_TECHNICIAN_ID

pytestmark = pytest.mark.integration

_TECHNICIAN_ID = TEST_TECHNICIAN_ID
_SUBMITTED_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_TELEGRAM_USER_ID = 424242


def test_warehouse_inventory_webhook_path_accepts_and_notifies_telegram(
    mongo_database: Database,
) -> None:
    stack = build_warehouse_settlement_stack(
        mongo_database,
        product_mapping={"Кофе": "coffee"},
        pack_size=Decimal("20"),
        unit=ProductUnit.PIECE,
    )

    response = post_warehouse_inventory(
        stack,
        technician_id=_TECHNICIAN_ID,
        coffee="2",
        nonce="inv-wh-1",
        submitted_at=_SUBMITTED_AT,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["purpose"] == "technician_warehouse_inventory"
    assert body["event_id"]
    drained = drain_handler_sync(
        stack,
        TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
    )
    assert drained >= 1
    stack.inventory_telegram_bot.send_message.assert_awaited_once_with(
        chat_id=_TELEGRAM_USER_ID,
        text="Остатки склада приняты.",
    )
