from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Literal

import pytest

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
)
from src.infrastructure.mongodb.sales_monitoring_audit_documents import (
    no_sales_audit_document_id,
    no_sales_episode_document_id,
)
from src.infrastructure.sales_monitoring.backfill_no_sales_episodes import run_backfill
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

_MACHINE_ID = MachineId("101")
_OPENED_AT = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
_CLEARED_AT = datetime(2026, 7, 28, 15, 0, tzinfo=UTC)
_LAST_SALE_AT = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
_OTHER_OPENED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def _opened(
    *,
    event_id: EventId | None = None,
    opened_at: datetime = _OPENED_AT,
) -> SalesMonitoringNoSalesStaleOpened:
    eid = event_id or EventId(
        f"sales-monitoring-no-sales-stale-opened:{_MACHINE_ID.value}:{opened_at.isoformat()}"
    )
    return SalesMonitoringNoSalesStaleOpened(
        event_id=eid,
        machine_id=_MACHINE_ID,
        opened_at=opened_at,
        occurred_at=opened_at,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-1"),
        assigned_technician_display="Иван",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def _cleared(
    *,
    opened_event_id: EventId,
    cleared_at: datetime = _CLEARED_AT,
    opened_at: datetime = _OPENED_AT,
    clear_trigger: Literal["sale", "exclude"] | None = "sale",
) -> SalesMonitoringNoSalesStaleCleared:
    return SalesMonitoringNoSalesStaleCleared(
        event_id=EventId(
            f"sales-monitoring-no-sales-stale-cleared:{_MACHINE_ID.value}:{cleared_at.isoformat()}"
        ),
        machine_id=_MACHINE_ID,
        opened_event_id=opened_event_id,
        opened_at=opened_at,
        cleared_at=cleared_at,
        occurred_at=cleared_at,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-1"),
        assigned_technician_display="Иван",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
        clear_trigger=clear_trigger,
        bypass_active=False if clear_trigger is not None else None,
    )


def _seed_other_sticky(store: InMemorySalesMonitoringAuditStore) -> dict[str, object]:
    sticky_id = no_sales_audit_document_id(_MACHINE_ID)
    sticky: dict[str, object] = {
        "_id": sticky_id,
        "kind": "no_sales",
        "machine_id": _MACHINE_ID.value,
        "status": "open",
        "opened_at": _OTHER_OPENED_AT,
        "opened_event_id": "other-cycle-open-id",
        "cleared_at": None,
    }
    store.upsert_audit_document(sticky)
    return deepcopy(dict(store.get(sticky_id) or {}))


def test_backfill_opened_cleared_pair_writes_one_episode() -> None:
    """happy: Opened+Cleared с одним opened id → один episode с полями clear."""
    store = InMemorySalesMonitoringAuditStore()
    sticky_before = _seed_other_sticky(store)
    opened = _opened()
    cleared = _cleared(opened_event_id=opened.event_id)

    count = run_backfill(events=(opened, cleared), audit_store=store, dry_run=False)

    episode_id = no_sales_episode_document_id(_MACHINE_ID, opened.event_id)
    episode = store.get(episode_id)
    assert count == 1
    assert episode is not None
    assert episode["cleared_at"] == _CLEARED_AT
    assert episode["opened_event_id"] == opened.event_id.value
    assert store.get(str(sticky_before["_id"])) == sticky_before


def test_backfill_repeat_and_dry_run_do_not_duplicate() -> None:
    """edge: повторный run не плодит _id; dry_run возвращает count и не пишет."""
    store = InMemorySalesMonitoringAuditStore()
    opened = _opened()
    cleared = _cleared(opened_event_id=opened.event_id)
    episode_id = no_sales_episode_document_id(_MACHINE_ID, opened.event_id)

    dry_count = run_backfill(events=(opened, cleared), audit_store=store, dry_run=True)
    assert dry_count == 1
    assert store.get(episode_id) is None

    first = run_backfill(events=(opened, cleared), audit_store=store, dry_run=False)
    second = run_backfill(events=(opened, cleared), audit_store=store, dry_run=False)
    assert first == 1
    assert second == 1
    assert store.get(episode_id) is not None
    episodes = [doc for doc in store._documents.values() if doc.get("kind") == "no_sales_episode"]
    assert len(episodes) == 1


def test_backfill_does_not_mutate_sticky() -> None:
    """edge: после backfill sticky document bitwise/fields равны до-снимку."""
    store = InMemorySalesMonitoringAuditStore()
    sticky_before = _seed_other_sticky(store)
    opened = _opened()
    cleared = _cleared(opened_event_id=opened.event_id)

    run_backfill(events=(opened, cleared), audit_store=store, dry_run=False)

    sticky_after = store.get(str(sticky_before["_id"]))
    assert sticky_after == sticky_before


def test_backfill_cleared_without_opened_still_writes_episode() -> None:
    """edge: Cleared без парного Opened → episode с opened_at с события clear."""
    store = InMemorySalesMonitoringAuditStore()
    orphan_opened_id = EventId("orphan-opened-event-id")
    cleared = _cleared(opened_event_id=orphan_opened_id, clear_trigger=None)

    count = run_backfill(events=(cleared,), audit_store=store, dry_run=False)

    episode_id = no_sales_episode_document_id(_MACHINE_ID, orphan_opened_id)
    episode = store.get(episode_id)
    assert count == 1
    assert episode is not None
    assert episode["opened_at"] == _OPENED_AT
    assert episode["cleared_at"] == _CLEARED_AT
    assert episode["opened_event_id"] == orphan_opened_id.value


def test_backfill_requires_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """error / self-check: backfill requires MONGODB_URI."""
    from src.config.mongodb import MongoSettings

    class _FakeSettings:
        mongodb = MongoSettings()

    monkeypatch.setattr(
        "scripts.backfill_no_sales_episodes.get_settings",
        lambda: _FakeSettings(),
    )
    from scripts.backfill_no_sales_episodes import main

    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 1
