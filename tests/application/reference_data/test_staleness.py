from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.application.reference_data.staleness import evaluate_staleness

_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def _snapshot(fetched_at: datetime) -> ReferenceDataSnapshot:
    return ReferenceDataSnapshot(
        source_id=ReferenceDataSourceId.BOT_USERS,
        rows=(("id",),),
        content_hash="sha256:x",
        last_fetched_at=fetched_at,
        content_updated_at=fetched_at,
    )


def test_fresh_snapshot_is_not_stale() -> None:
    snapshot = _snapshot(_NOW - timedelta(seconds=100))
    assert evaluate_staleness(snapshot, now=_NOW, threshold_seconds=300) is False


def test_old_snapshot_is_stale() -> None:
    snapshot = _snapshot(_NOW - timedelta(seconds=400))
    assert evaluate_staleness(snapshot, now=_NOW, threshold_seconds=300) is True


def test_missing_snapshot_is_not_reported_as_stale() -> None:
    assert evaluate_staleness(None, now=_NOW, threshold_seconds=300) is False
