from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.application.machine_pnl.models import (
    FULL_SLICE_KEY,
    PeriodPnl,
    PnlWarning,
    make_pnl_id,
)
from src.application.machine_pnl.opex_breakdown import (
    OPEX_BREAKDOWN_KEYS,
    empty_opex_breakdown,
)
from src.domain.ids import MachineId
from src.infrastructure.mongodb.machine_period_pnl import (
    MongoPeriodPnlStore,
    period_pnl_from_document,
)


def _pnl(
    *,
    revenue: str = "100.00",
    period_id: str = "p-1",
    location_id: str | None = None,
    technician_id: str | None = None,
) -> PeriodPnl:
    return PeriodPnl(
        pnl_id=make_pnl_id(period_id),
        period_id=period_id,
        slice_key=FULL_SLICE_KEY,
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        closed_at=datetime(2026, 1, 10, tzinfo=UTC),
        revenue=Decimal(revenue),
        cogs_expected=Decimal("40.00"),
        cogs_actual=Decimal("42.50"),
        allocated_shortage=Decimal("0.00"),
        allocated_surplus=Decimal("0.00"),
        opex=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        net_before_residual=Decimal("57.50"),
        net_after_shortage=Decimal("57.50"),
        warnings=(PnlWarning(code="null_price", message="null_price_count=2"),),
        location_id=location_id,
        technician_id=technician_id,
    )


def test_period_pnl_store_upsert_roundtrip() -> None:
    collection = mongomock.MongoClient().db.machine_period_pnl
    store = MongoPeriodPnlStore.from_collection(collection)

    store.save(_pnl(revenue="100.00"), source_session_id="sess-1")
    loaded = store.get(make_pnl_id("p-1"))
    assert loaded == _pnl(revenue="100.00")

    raw = collection.find_one({"period_id": "p-1"})
    assert raw is not None
    assert raw["revenue"] == "100.00"
    assert raw["cogs_actual"] == "42.50"
    assert raw["source_session_id"] == "sess-1"
    assert isinstance(raw["revenue"], str)
    assert "unallocated_residual_by_sku" not in raw
    assert raw["opex_breakdown"] == [[k, "0.00"] for k, _ in empty_opex_breakdown()]
    assert raw["warnings"] == [{"code": "null_price", "message": "null_price_count=2", "sku": None}]

    store.save(_pnl(revenue="200.00"), source_session_id="sess-2")
    reloaded = store.get(make_pnl_id("p-1"))
    assert reloaded is not None
    assert reloaded.revenue == Decimal("200.00")
    raw2 = collection.find_one({"period_id": "p-1"})
    assert raw2 is not None
    assert raw2["revenue"] == "200.00"
    assert raw2["source_session_id"] == "sess-2"
    assert collection.count_documents({}) == 1


def test_period_pnl_mongo_indexes_pnl_id_and_period_slice() -> None:
    collection = mongomock.MongoClient().db.machine_period_pnl
    MongoPeriodPnlStore.from_collection(collection)
    indexes = collection.index_information()
    assert "machine_period_pnl_pnl_id_unique" in indexes
    assert indexes["machine_period_pnl_pnl_id_unique"]["unique"] is True
    assert "machine_period_pnl_period_slice_unique" in indexes
    assert indexes["machine_period_pnl_period_slice_unique"]["unique"] is True


def test_period_pnl_store_upsert_by_pnl_id_mongo() -> None:
    collection = mongomock.MongoClient().db.machine_period_pnl
    store = MongoPeriodPnlStore.from_collection(collection)
    pnl = _pnl(period_id="p-1")
    store.save(pnl, source_session_id="sess-1")
    loaded = store.get(make_pnl_id("p-1"))
    assert loaded == pnl
    raw = collection.find_one({"pnl_id": make_pnl_id("p-1")})
    assert raw is not None
    assert raw["slice_key"] == "full"
    assert "machine_period_pnl_period_id_unique" not in collection.index_information()


def test_period_pnl_opex_breakdown_roundtrip() -> None:
    collection = mongomock.MongoClient().db.machine_period_pnl
    store = MongoPeriodPnlStore.from_collection(collection)
    pnl = _pnl()
    store.save(pnl, source_session_id="s1")
    loaded = store.get(make_pnl_id("p-1"))
    assert loaded is not None
    assert loaded.opex_breakdown == empty_opex_breakdown()
    raw = collection.find_one({"period_id": "p-1"})
    assert raw is not None
    assert "unallocated_residual_by_sku" not in raw
    assert "opex_breakdown" in raw


def test_period_pnl_tax_null_mongo_roundtrip() -> None:
    collection = mongomock.MongoClient().db.machine_period_pnl
    store = MongoPeriodPnlStore.from_collection(collection)

    base = dict(empty_opex_breakdown())
    base["tax"] = None
    breakdown = tuple((k, base[k]) for k in OPEX_BREAKDOWN_KEYS)
    pnl = PeriodPnl(
        pnl_id=make_pnl_id("p-tax-null"),
        period_id="p-tax-null",
        slice_key=FULL_SLICE_KEY,
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        closed_at=datetime(2026, 1, 10, tzinfo=UTC),
        revenue=Decimal("100.00"),
        cogs_expected=Decimal("0.00"),
        cogs_actual=Decimal("0.00"),
        allocated_shortage=Decimal("0.00"),
        allocated_surplus=Decimal("0.00"),
        opex=Decimal("5.00"),
        opex_breakdown=breakdown,
        net_before_residual=Decimal("95.00"),
        net_after_shortage=Decimal("95.00"),
        warnings=(PnlWarning(code="tax_pending_manual", message="pending"),),
    )
    store.save(pnl, source_session_id="sess-1")
    loaded = store.get(make_pnl_id("p-tax-null"))
    assert loaded is not None
    assert dict(loaded.opex_breakdown)["tax"] is None
    assert any(w.code == "tax_pending_manual" for w in loaded.warnings)

    raw = collection.find_one({"period_id": "p-tax-null"})
    assert raw is not None
    tax_pair = next(pair for pair in raw["opex_breakdown"] if pair[0] == "tax")
    assert tax_pair[1] is None


def test_period_pnl_mongo_omits_unallocated_and_ignores_legacy() -> None:
    doc = {
        "period_id": "legacy",
        "machine_id": "101",
        "opened_at": datetime(2026, 1, 1, tzinfo=UTC),
        "closed_at": datetime(2026, 1, 10, tzinfo=UTC),
        "revenue": "1.00",
        "cogs_expected": "0.00",
        "cogs_actual": "0.00",
        "allocated_shortage": "0.00",
        "allocated_surplus": "0.00",
        "unallocated_residual_by_sku": [["SKU", "1.00"]],  # legacy
        "opex": "0.00",
        "opex_breakdown": [
            ["rent_fixed", "0.00"],
            ["rent_percent", "0.00"],
            ["patent", "0.00"],
            ["tax", "0.00"],
            ["acquiring_percent", "0.00"],
            ["acquiring_per_sale", "0.00"],
            ["terminal", "0.00"],
            ["labor", "0.00"],
            ["route_fuel", "0.00"],
        ],
        "net_before_residual": "1.00",
        "net_after_shortage": "1.00",
        "warnings": [],
    }
    pnl = period_pnl_from_document(doc)
    assert not hasattr(pnl, "unallocated_residual_by_sku")


def test_period_pnl_from_document_legacy_missing_location_technician() -> None:
    doc = {
        "period_id": "legacy",
        "machine_id": "101",
        "opened_at": datetime(2026, 1, 1, tzinfo=UTC),
        "closed_at": datetime(2026, 1, 10, tzinfo=UTC),
        "revenue": "1.00",
        "cogs_expected": "0.00",
        "cogs_actual": "0.00",
        "allocated_shortage": "0.00",
        "allocated_surplus": "0.00",
        "opex": "0.00",
        "opex_breakdown": [[k, "0.00"] for k, _ in empty_opex_breakdown()],
        "net_before_residual": "1.00",
        "net_after_shortage": "1.00",
        "warnings": [],
    }
    pnl = period_pnl_from_document(doc)
    assert pnl.location_id is None
    assert pnl.technician_id is None


def test_period_pnl_mongo_roundtrip_location_technician() -> None:
    collection = mongomock.MongoClient().db.machine_period_pnl
    store = MongoPeriodPnlStore.from_collection(collection)
    filled = _pnl(location_id="loc-a", technician_id="tech-1")
    store.save(filled, source_session_id="s1")
    loaded = store.get(filled.pnl_id)
    assert loaded is not None
    assert loaded.location_id == "loc-a"
    assert loaded.technician_id == "tech-1"
