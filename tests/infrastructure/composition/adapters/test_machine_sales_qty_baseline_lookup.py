from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.composition.adapters.machine_sales_qty_baseline_lookup import (
    MachineSalesStoreQtyBaselineLookup,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_TZ = ZoneInfo("Asia/Yekaterinburg")
_MACHINE = MachineId("101")
_AS_OF = date(2026, 7, 27)
_INGESTED = datetime(2026, 7, 28, 8, 0, tzinfo=_TZ)


def test_adapter_baseline_avg_qty_happy() -> None:
    store = InMemoryMachineSalesStore()
    for i, offset in enumerate(range(1, 8)):
        day = _AS_OF - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        store.insert_if_absent(
            MachineSale(
                source_id=f"s-{i}",
                machine_id=_MACHINE,
                product_code="sku",
                quantity=Decimal("100"),
                occurred_at=datetime.combine(day, time(12, 0), tzinfo=_TZ),
                ingested_at=_INGESTED,
                price=Decimal("1"),
            )
        )
    lookup = MachineSalesStoreQtyBaselineLookup(
        sales=store,
        timezone=_TZ,
        days_for_average=14,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
    )
    assert lookup.baseline_avg_qty(machine_id=_MACHINE, as_of_day=_AS_OF) == Decimal("100")


def test_adapter_baseline_avg_qty_insufficient_returns_none() -> None:
    lookup = MachineSalesStoreQtyBaselineLookup(
        sales=InMemoryMachineSalesStore(),
        timezone=_TZ,
        days_for_average=14,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
    )
    assert lookup.baseline_avg_qty(machine_id=_MACHINE, as_of_day=_AS_OF) is None


def test_adapter_day_bucket_follows_lookup_timezone_not_service_display() -> None:
    """Near-midnight YEKT sale is weekday under SM TZ; Europe/Moscow buckets it as weekend."""
    service_display_tz = ZoneInfo("Europe/Moscow")
    store = InMemoryMachineSalesStore()
    # 2026-07-27 00:30 Asia/Yekaterinburg == 2026-07-26 22:30 Europe/Moscow (Sunday)
    store.insert_if_absent(
        MachineSale(
            source_id="boundary",
            machine_id=_MACHINE,
            product_code="sku",
            quantity=Decimal("50"),
            occurred_at=datetime(2026, 7, 27, 0, 30, tzinfo=_TZ),
            ingested_at=_INGESTED,
            price=Decimal("1"),
        )
    )
    as_of = date(2026, 7, 28)  # Tuesday → like-day = weekday
    yekt_lookup = MachineSalesStoreQtyBaselineLookup(
        sales=store,
        timezone=_TZ,
        days_for_average=14,
        baseline_min_points=1,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
    )
    moscow_lookup = MachineSalesStoreQtyBaselineLookup(
        sales=store,
        timezone=service_display_tz,
        days_for_average=14,
        baseline_min_points=1,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
    )
    assert yekt_lookup.baseline_avg_qty(machine_id=_MACHINE, as_of_day=as_of) == Decimal("50")
    assert moscow_lookup.baseline_avg_qty(machine_id=_MACHINE, as_of_day=as_of) is None
