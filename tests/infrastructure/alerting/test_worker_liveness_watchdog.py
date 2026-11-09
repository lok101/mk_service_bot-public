from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.config.worker_liveness import WORKER_LIVENESS_TARGETS_V1, WorkerLivenessTarget
from src.infrastructure.alerting import worker_liveness_watchdog as watchdog_mod
from src.infrastructure.alerting.worker_liveness_watchdog import WorkerLivenessWatchdog

_NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
_TARGET = WorkerLivenessTarget(
    name="sales-monitoring",
    status_collection="sales_monitoring_worker_status",
)


class _FakeDb:
    def __init__(self, collections: dict[str, Any]) -> None:
        self._collections = collections
        self.fail_collections: set[str] = set()

    def __getitem__(self, name: str) -> Any:
        if name in self.fail_collections:
            raise RuntimeError(f"mongo read failed: {name}")
        return self._collections[name]


class _FakeCollection:
    def __init__(self, doc: dict[str, Any] | None) -> None:
        self._doc = doc

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None:
        del filter
        return self._doc


def _watchdog(
    *,
    db: _FakeDb,
    sends: list[str],
    alerts_enabled: bool = True,
    stale_seconds: int = 300,
    cooldown_seconds: int = 1800,
    targets: tuple[WorkerLivenessTarget, ...] = (_TARGET,),
) -> WorkerLivenessWatchdog:
    def send(text: str) -> None:
        sends.append(text)

    return WorkerLivenessWatchdog(
        targets=targets,
        stale_seconds=stale_seconds,
        alert_cooldown_seconds=cooldown_seconds,
        database=db,
        send_alert=send if alerts_enabled else None,
        now=lambda: _NOW,
    )


def test_watchdog_alerts_on_stale_or_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stale_at = (_NOW - timedelta(seconds=400)).isoformat()
    db = _FakeDb(
        {
            "sales_monitoring_worker_status": _FakeCollection(
                {"_id": "worker", "last_heartbeat_at": stale_at},
            ),
            "matrix_worker_status": _FakeCollection(None),
        }
    )
    sends: list[str] = []
    targets = (
        _TARGET,
        WorkerLivenessTarget(name="matrix", status_collection="matrix_worker_status"),
    )
    wd = _watchdog(db=db, sends=sends, targets=targets)

    with caplog.at_level(logging.INFO):
        wd.check_once()

    assert len(sends) == 2
    assert any("sales-monitoring" in text for text in sends)
    assert any("matrix" in text for text in sends)
    assert any("worker_liveness_watchdog_alert" in r.getMessage() for r in caplog.records)


def test_watchdog_fresh_heartbeat_and_cooldown_suppress(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fresh_at = (_NOW - timedelta(seconds=60)).isoformat()
    db = _FakeDb(
        {
            "sales_monitoring_worker_status": _FakeCollection(
                {"_id": "worker", "last_heartbeat_at": fresh_at},
            ),
        }
    )
    sends: list[str] = []
    wd = _watchdog(db=db, sends=sends)

    with caplog.at_level(logging.INFO):
        wd.check_once()
    assert sends == []

    db._collections["sales_monitoring_worker_status"] = _FakeCollection(None)
    with caplog.at_level(logging.INFO):
        wd.check_once()
        wd.check_once()

    assert len(sends) == 1
    assert any("cooldown" in r.getMessage() for r in caplog.records)


def test_watchdog_mongo_read_failure_logged_loop_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _FakeDb(
        {
            "sales_monitoring_worker_status": _FakeCollection(None),
            "matrix_worker_status": _FakeCollection(None),
        }
    )
    db.fail_collections.add("sales_monitoring_worker_status")
    sends: list[str] = []
    targets = (
        _TARGET,
        WorkerLivenessTarget(name="matrix", status_collection="matrix_worker_status"),
    )
    wd = _watchdog(db=db, sends=sends, targets=targets)

    with caplog.at_level(logging.WARNING):
        wd.check_once()

    assert len(sends) == 1
    assert "matrix" in sends[0]
    assert any(
        "sales-monitoring" in r.getMessage() or "mongo" in r.getMessage().lower()
        for r in caplog.records
    )


def test_watchdog_skips_when_alerts_disabled(caplog: pytest.LogCaptureFixture) -> None:
    db = _FakeDb({"sales_monitoring_worker_status": _FakeCollection(None)})
    sends: list[str] = []
    wd = _watchdog(db=db, sends=sends, alerts_enabled=False)

    with caplog.at_level(logging.INFO):
        wd.check_once()

    assert sends == []
    assert any("alerts_disabled" in r.getMessage() for r in caplog.records)


def test_watchdog_targets_v1_exclude_event_reminders() -> None:
    names = {t.name for t in WORKER_LIVENESS_TARGETS_V1}
    collections = {t.status_collection for t in WORKER_LIVENESS_TARGETS_V1}
    assert "event-reminders" not in names
    assert len(WORKER_LIVENESS_TARGETS_V1) == 6
    assert "effects-worker" in names
    assert "effects_worker_status" in collections
    assert "event_reminders_worker_status" not in collections
    assert hasattr(watchdog_mod, "WorkerLivenessWatchdog")
