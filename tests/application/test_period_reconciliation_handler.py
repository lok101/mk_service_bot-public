from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from tests.application.close_period_helpers import (
    CLOSED,
    build_close_period_handler,
    second_revision_event,
)

from src.domain.ids import TechnicianId


def test_handler_posts_accountability_on_complete() -> None:
    handler, repo, settlement_repo = build_close_period_handler(sale_occurred_at=CLOSED)
    event = second_revision_event()

    asyncio.run(handler.process(event))

    snapshot = repo.get_by_period_id("rev-1:rev-2")
    assert snapshot is not None
    assert snapshot.status == "complete"
    assert snapshot.ledger_posted is True
    assert repo.ledger_posted_periods == ["rev-1:rev-2"]
    aggregate = settlement_repo.get(TechnicianId("tech-b"))
    assert aggregate.net_balance_by_sku() == {}


def test_handler_skips_when_pending_sales() -> None:
    handler, repo, settlement_repo = build_close_period_handler(
        sale_occurred_at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
    )
    event = second_revision_event()

    asyncio.run(handler.process(event))

    snapshot = repo.get_by_period_id("rev-1:rev-2")
    assert snapshot is not None
    assert snapshot.status == "pending_sales"
    assert snapshot.ledger_posted is False
    assert repo.ledger_posted_periods == []
    assert settlement_repo.get(TechnicianId("tech-b")).net_balance_by_sku() == {}


def test_handler_skips_when_already_posted() -> None:
    handler, repo, settlement_repo = build_close_period_handler(sale_occurred_at=CLOSED)
    event = second_revision_event()
    asyncio.run(handler.process(event))
    assert repo.ledger_posted_periods == ["rev-1:rev-2"]

    asyncio.run(handler.process(event))

    assert repo.ledger_posted_periods == ["rev-1:rev-2"]
    assert len(settlement_repo.events) == 1


def test_handler_skips_when_already_reconciled() -> None:
    handler, repo, settlement_repo = build_close_period_handler(sale_occurred_at=CLOSED)
    event = second_revision_event()
    snapshot = handler.close_period.execute(closing_event=event)
    assert snapshot is not None
    repo.save(replace(snapshot, reconciled=True))
    asyncio.run(handler.process(event))
    assert repo.ledger_posted_periods == []
    assert settlement_repo.events == []
