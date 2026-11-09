from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import mongomock

from src.application.machine_pnl.models import PnlWarning
from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.application.machine_pnl.opex_breakdown import empty_opex_breakdown
from src.domain.ids import MachineId
from src.infrastructure.mongodb.machine_pnl_month_snapshot import MongoMonthPnlSnapshotStore


def _snap(*, revenue: str = "10.00") -> MonthPnlSnapshot:
    return MonthPnlSnapshot(
        machine_id=MachineId("101"),
        location_id="loc-a",
        technician_id="tech-1",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        revenue=Decimal(revenue),
        revenue_known_as_of=date(2026, 6, 30),
        cogs_expected=Decimal("4.00"),
        cogs_actual_fact=Decimal("5.00"),
        cogs_actual_estimate=Decimal("0.00"),
        allocated_shortage_fact=Decimal("1.00"),
        allocated_shortage_estimate=Decimal("0.00"),
        allocated_surplus_fact=Decimal("0.00"),
        allocated_surplus_estimate=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        opex_known_total=Decimal("2.00"),
        net_theory=Decimal("4.00"),
        machine_gap=Decimal("1.00"),
        net_machine=Decimal("3.00"),
        tech_gap=Decimal("1.00"),
        net_after_tech=Decimal("2.00"),
        coverage_days=30,
        days_in_month=30,
        coverage_pct=Decimal("100"),
        projection_basis="fact",
        warnings=(PnlWarning(code="x", message="m"),),
        last_recomputed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def test_mongo_month_snapshot_upsert_same_key_one_document() -> None:
    collection = mongomock.MongoClient().db.machine_pnl_month_snapshot
    store = MongoMonthPnlSnapshotStore.from_collection(collection)
    store.upsert(_snap(revenue="10.00"))
    store.upsert(_snap(revenue="20.00"))
    loaded = store.get(MachineId("101"), date(2026, 6, 1))
    assert loaded is not None
    assert loaded.revenue == Decimal("20.00")
    assert collection.count_documents({}) == 1


def test_mongo_month_snapshot_lists_by_period_starts() -> None:
    collection = mongomock.MongoClient().db.machine_pnl_month_snapshot
    store = MongoMonthPnlSnapshotStore.from_collection(collection)
    store.upsert(_snap(revenue="10.00"))
    store.upsert(replace(_snap(revenue="3.00"), machine_id=MachineId("102")))
    store.upsert(
        replace(
            _snap(revenue="8.00"),
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
        )
    )
    store.upsert(
        replace(
            _snap(revenue="1.00"),
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )
    )
    listed = store.list_for_period_starts((date(2026, 6, 1), date(2026, 5, 1)))
    keys = {(item.machine_id.value, item.period_start) for item in listed}
    assert keys == {
        ("101", date(2026, 6, 1)),
        ("102", date(2026, 6, 1)),
        ("101", date(2026, 5, 1)),
    }


def test_month_snapshot_roundtrip_company_id() -> None:
    collection = mongomock.MongoClient().db.month
    store = MongoMonthPnlSnapshotStore.from_collection(collection)
    store.upsert(replace(_snap(), company_id=42))
    loaded = store.get(MachineId("101"), date(2026, 6, 1))
    assert loaded is not None
    assert loaded.company_id == 42


def test_month_snapshot_company_id_none_when_missing_on_document() -> None:
    collection = mongomock.MongoClient().db.month
    store = MongoMonthPnlSnapshotStore.from_collection(collection)
    store.upsert(_snap())
    loaded = store.get(MachineId("101"), date(2026, 6, 1))
    assert loaded is not None
    assert loaded.company_id is None


def test_month_snapshot_has_no_company_name_field() -> None:
    fields = MonthPnlSnapshot.__dataclass_fields__
    assert "company_id" in fields
    assert "company_name" not in fields
