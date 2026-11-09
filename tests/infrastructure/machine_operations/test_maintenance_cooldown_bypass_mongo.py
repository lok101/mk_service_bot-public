from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import mongomock

from src.infrastructure.machine_operations.maintenance_cooldown_bypass_mongo import (
    MongoMaintenanceCooldownBypassStore,
)

_MSK = ZoneInfo("Europe/Moscow")


def _store() -> MongoMaintenanceCooldownBypassStore:
    collection = mongomock.MongoClient().db.maintenance_cooldown_bypass
    return MongoMaintenanceCooldownBypassStore(
        _collection=collection,
        service_calendar_timezone=_MSK,
        service_day_end_hour=6,
    )


def test_upsert_and_get_snapshot() -> None:
    store = _store()
    activated_at = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)
    snapshot = store.upsert_for_today(
        activated_at=activated_at,
        reason="test",
        service_calendar_timezone=_MSK,
    )
    assert snapshot.service_date == date(2026, 7, 8)
    assert store.get_snapshot() == snapshot


def test_get_active_returns_snapshot_before_expiry() -> None:
    store = _store()
    store.upsert_for_today(
        activated_at=datetime(2026, 7, 8, 7, 0, tzinfo=UTC),
        reason=None,
        service_calendar_timezone=_MSK,
    )
    active = store.get_active(checked_at=datetime(2026, 7, 9, 5, 59, tzinfo=_MSK))
    assert active is not None
    assert active.service_date == date(2026, 7, 8)


def test_get_active_returns_none_at_expiry() -> None:
    store = _store()
    store.upsert_for_today(
        activated_at=datetime(2026, 7, 8, 7, 0, tzinfo=UTC),
        reason=None,
        service_calendar_timezone=_MSK,
    )
    assert store.get_active(checked_at=datetime(2026, 7, 9, 6, 0, tzinfo=_MSK)) is None


def test_clear_removes_document() -> None:
    store = _store()
    store.upsert_for_today(
        activated_at=datetime(2026, 7, 8, 7, 0, tzinfo=UTC),
        reason=None,
        service_calendar_timezone=_MSK,
    )
    assert store.clear() is True
    assert store.get_snapshot() is None
    assert store.clear() is False


def test_upsert_at_0200_uses_previous_operational_day() -> None:
    store = _store()
    snapshot = store.upsert_for_today(
        activated_at=datetime(2026, 7, 9, 2, 0, tzinfo=_MSK),
        reason=None,
        service_calendar_timezone=_MSK,
    )
    assert snapshot.service_date == date(2026, 7, 8)
