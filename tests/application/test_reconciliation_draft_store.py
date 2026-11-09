from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.application.technician_settlement.draft import (
    ReconciliationDraft,
    plan_from_storage,
    plan_to_storage,
)
from src.infrastructure.mongodb.reconciliation_drafts import MongoReconciliationDraftStore
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore


def _inventory_draft(**overrides: object) -> ReconciliationDraft:
    draft = ReconciliationDraft(
        technician_id="10001",
        kind="inventory",
        warehouse_inventory_id="inv-2",
        warehouse_inventory_moment=datetime(2026, 6, 10, tzinfo=UTC),
        plan={"mode": "inventory_delta", "period_ids": ["p1"]},
        updated_at=datetime(2026, 6, 15, tzinfo=UTC),
        anchor_at=datetime(2026, 6, 15, tzinfo=UTC),
    )
    if not overrides:
        return draft
    return replace(draft, **overrides)  # type: ignore[arg-type]


def test_draft_store_upsert_get_delete_by_composite_id() -> None:
    store = InMemoryReconciliationDraftStore()
    draft = _inventory_draft()
    store.upsert(draft)
    assert store.get("10001", "inventory") == draft
    store.upsert(replace(draft, plan={"mode": "inventory_delta", "period_ids": ["p2"]}))
    loaded = store.get("10001", "inventory")
    assert loaded is not None
    assert loaded.plan["period_ids"] == ["p2"]
    store.delete("10001", "inventory")
    assert store.get("10001", "inventory") is None


def test_draft_store_list_by_kind_sorted_by_technician_id() -> None:
    store = InMemoryReconciliationDraftStore()
    store.upsert(_inventory_draft(technician_id="10003"))
    store.upsert(
        ReconciliationDraft(
            technician_id="10002",
            kind="exit",
            warehouse_inventory_id="exit-1",
            warehouse_inventory_moment=datetime(2026, 6, 20, tzinfo=UTC),
            plan={"mode": "exit"},
            updated_at=datetime(2026, 6, 20, tzinfo=UTC),
            anchor_at=None,
        ),
    )
    store.upsert(_inventory_draft(technician_id="10001"))
    inventory = store.list_by_kind("inventory")
    assert [draft.technician_id for draft in inventory] == ["10001", "10003"]
    exit_drafts = store.list_by_kind("exit")
    assert len(exit_drafts) == 1
    assert exit_drafts[0].technician_id == "10002"


def test_in_memory_draft_store_round_trips_money_maps_like_mongo() -> None:
    store = InMemoryReconciliationDraftStore()
    store.upsert(
        _inventory_draft(
            plan={
                "mode": "inventory_delta",
                "warehouse_delta_by_sku": {"sku-a": Decimal("3.00")},
            },
        ),
    )
    loaded = store.get("10001", "inventory")
    assert loaded is not None
    assert loaded.plan["warehouse_delta_by_sku"]["sku-a"] == Decimal("3.00")


def test_draft_plan_decimal_round_trip() -> None:
    plan = {
        "mode": "inventory_delta",
        "period_ids": ["p1"],
        "warehouse_delta_by_sku": {"sku-a": Decimal("12.50")},
        "residual_by_sku": {"sku-a": Decimal("-1.25")},
    }
    stored = plan_to_storage(plan)
    assert stored["warehouse_delta_by_sku"]["sku-a"] == "12.50"
    assert stored["residual_by_sku"]["sku-a"] == "-1.25"
    assert stored["mode"] == "inventory_delta"
    restored = plan_from_storage(stored)
    assert restored["warehouse_delta_by_sku"]["sku-a"] == Decimal("12.50")
    assert restored["residual_by_sku"]["sku-a"] == Decimal("-1.25")


def test_mongo_draft_store_round_trip_decimal_strings() -> None:
    collection = mongomock.MongoClient().db.reconciliation_drafts
    store = MongoReconciliationDraftStore.from_collection(collection)
    draft = _inventory_draft(
        plan={
            "mode": "inventory_delta",
            "period_ids": ["p1"],
            "warehouse_delta_by_sku": {"sku-a": Decimal("3.00")},
            "ledger_balance_session": {"sku-a": Decimal("1.5")},
            "residual_by_sku": {"sku-a": Decimal("4.5")},
        },
    )
    store.upsert(draft)
    raw = collection.find_one({"_id": "10001:inventory"})
    assert raw is not None
    assert raw["plan"]["warehouse_delta_by_sku"]["sku-a"] == "3.00"
    assert raw["plan"]["residual_by_sku"]["sku-a"] == "4.5"
    loaded = store.get("10001", "inventory")
    assert loaded is not None
    assert loaded.plan["warehouse_delta_by_sku"]["sku-a"] == Decimal("3.00")
    assert loaded.plan["ledger_balance_session"]["sku-a"] == Decimal("1.5")
    assert loaded.plan["residual_by_sku"]["sku-a"] == Decimal("4.5")
    assert loaded.kind == "inventory"
    assert loaded.anchor_at == datetime(2026, 6, 15, tzinfo=UTC)


def test_mongo_exit_draft_round_trip_null_anchor() -> None:
    collection = mongomock.MongoClient().db.reconciliation_drafts
    store = MongoReconciliationDraftStore.from_collection(collection)
    draft = ReconciliationDraft(
        technician_id="10001",
        kind="exit",
        warehouse_inventory_id="exit-evt-1",
        warehouse_inventory_moment=datetime(2026, 6, 20, tzinfo=UTC),
        plan={
            "mode": "exit",
            "residual_by_sku": {"sku-a": Decimal("2.0")},
        },
        updated_at=datetime(2026, 6, 20, tzinfo=UTC),
        anchor_at=None,
    )
    store.upsert(draft)
    raw = collection.find_one({"_id": "10001:exit"})
    assert raw is not None
    assert raw["kind"] == "exit"
    assert raw["anchor_at"] is None
    loaded = store.get("10001", "exit")
    assert loaded is not None
    assert loaded.kind == "exit"
    assert loaded.anchor_at is None
    assert loaded.warehouse_inventory_id == "exit-evt-1"
    assert loaded.plan["residual_by_sku"]["sku-a"] == Decimal("2.0")
