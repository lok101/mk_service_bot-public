from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.composition.adapters.machine_sales_freshness_lookup import (
    MachineSalesStoreFreshnessLookup,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_MACHINE = MachineId("101")
_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_INGESTED = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)


def test_freshness_lookup_nulls_sale_outside_lookback() -> None:
    """edge: last_occurred_at старше lookback → None."""
    store = InMemoryMachineSalesStore()
    store.insert_if_absent(
        MachineSale(
            source_id="old",
            machine_id=_MACHINE,
            product_code="sku",
            quantity=Decimal("1"),
            occurred_at=_NOW - timedelta(days=40),
            ingested_at=_INGESTED,
            price=Decimal("1"),
        )
    )
    lookup = MachineSalesStoreFreshnessLookup(
        store=store,
        last_sale_lookup_days=28,
        clock=lambda: _NOW,
    )
    assert lookup.last_sale_at(_MACHINE) is None


def test_freshness_lookup_returns_cursor() -> None:
    """happy: global_sales_cursor делегирует store."""
    store = InMemoryMachineSalesStore()
    cursor = datetime(2026, 8, 21, 11, 30, tzinfo=UTC)
    store.save_global_cursor(cursor)
    lookup = MachineSalesStoreFreshnessLookup(
        store=store,
        last_sale_lookup_days=28,
        clock=lambda: _NOW,
    )
    assert lookup.global_sales_cursor() == cursor
