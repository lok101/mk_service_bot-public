from __future__ import annotations

from src.infrastructure.testing.kitshop_ingest_fakes import (
    InMemoryKitShopSalesBacklogStore,
)


def test_backlog_upsert_pending_idempotent() -> None:
    store = InMemoryKitShopSalesBacklogStore()
    assert store.upsert_pending(sale_id=100) is True
    assert store.upsert_pending(sale_id=100) is False
    assert store.get_status(100) == "pending"


def test_backlog_mark_done_and_hold() -> None:
    store = InMemoryKitShopSalesBacklogStore()
    store.upsert_pending(sale_id=1)
    store.mark_hold(sale_id=1, reason="no_machine_code")
    assert store.get_status(1) == "hold"
    store.mark_done(sale_id=1)
    assert store.get_status(1) == "done"


def test_backlog_claim_pending_includes_hold() -> None:
    # happy
    store = InMemoryKitShopSalesBacklogStore()
    store.upsert_pending(sale_id=1)
    store.upsert_pending(sale_id=2)
    store.mark_hold(sale_id=1, reason="no_machine_code")
    claimed = store.claim_pending(limit=10)
    assert claimed == [2, 1]


def test_backlog_claim_prefers_pending_over_older_hold() -> None:
    # happy: limit=1 не отдаёт более старый hold, пока есть pending
    store = InMemoryKitShopSalesBacklogStore()
    store.upsert_pending(sale_id=1)
    store.upsert_pending(sale_id=2)
    store.mark_hold(sale_id=1, reason="no_machine_code")
    assert store.claim_pending(limit=1) == [2]
    assert store.get_status(1) == "hold"
    assert store.get_status(2) == "pending"


def test_backlog_claim_returns_hold_when_no_pending() -> None:
    # edge: hold без pending всё ещё claim'ится
    store = InMemoryKitShopSalesBacklogStore()
    store.upsert_pending(sale_id=1)
    store.mark_hold(sale_id=1, reason="company_miss")
    assert store.claim_pending(limit=1) == [1]
    assert store.get_status(1) == "hold"
