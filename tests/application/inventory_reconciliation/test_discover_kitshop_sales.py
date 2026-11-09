from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.inventory_reconciliation.discover_kitshop_sales import (
    DiscoverKitShopSales,
)
from src.infrastructure.testing.kitshop_ingest_fakes import (
    FakeKitShopSalesGateway,
    InMemoryKitShopSalesBacklogStore,
    InMemoryKitShopSalesIngestCursorStore,
)


def test_discovery_upsert_idempotent() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    cursor = InMemoryKitShopSalesIngestCursorStore()
    gateway = FakeKitShopSalesGateway(
        list_sales=[
            {"sale_id": 100, "sale_datetime": datetime(2026, 9, 4, 12, 0, tzinfo=UTC)},
            {"sale_id": 101, "sale_datetime": datetime(2026, 9, 4, 13, 0, tzinfo=UTC)},
        ]
    )
    uc = DiscoverKitShopSales(
        gateway=gateway,
        backlog=backlog,
        cursor_store=cursor,
        overlap_seconds=0,
        initial_lookback=timedelta(days=7),
        now=lambda: datetime(2026, 9, 5, tzinfo=UTC),
    )
    r1 = uc.execute()
    r2 = uc.execute()
    assert r1.upserted == 2
    assert r2.upserted == 0
    assert backlog.get_status(100) == "pending"
    assert backlog.get_status(101) == "pending"


def test_discovery_advances_despite_hold_backlog() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=50)
    backlog.mark_hold(sale_id=50, reason="no_machine_code")
    cursor = InMemoryKitShopSalesIngestCursorStore()
    cursor.save(datetime(2026, 9, 3, tzinfo=UTC))
    gateway = FakeKitShopSalesGateway(
        list_sales=[
            {"sale_id": 200, "sale_datetime": datetime(2026, 9, 4, 15, 0, tzinfo=UTC)},
        ]
    )
    uc = DiscoverKitShopSales(
        gateway=gateway,
        backlog=backlog,
        cursor_store=cursor,
        overlap_seconds=1800,
        initial_lookback=timedelta(days=7),
        now=lambda: datetime(2026, 9, 5, tzinfo=UTC),
    )
    uc.execute()
    assert backlog.get_status(200) == "pending"
    assert cursor.load() is not None
    assert cursor.load() >= datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
