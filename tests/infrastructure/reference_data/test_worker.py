from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.reference_data.sync import SyncReferenceData
from src.infrastructure.reference_data.memory_store import (
    InMemoryReferenceDataSnapshotStore,
)
from src.infrastructure.reference_data.worker import ReferenceDataSyncWorker

_SID = ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS
_HEADER = ["id локации", "имя локации", "имя техника", "id техника"]
_ROW = ["129", "Локация 1", "Иван", "tech-1"]
_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


class _Reader:
    def read_rows(self, source_id):
        return [_HEADER, _ROW]


def _build_worker(store, now=lambda: _NOW) -> ReferenceDataSyncWorker:
    provider = ReferenceDataProvider()
    sync = SyncReferenceData(
        reader=_Reader(),
        store=store,
        provider=provider,
        source_ids=(_SID,),
        now=now,
    )
    return ReferenceDataSyncWorker(
        sync=sync,
        store=store,
        sync_interval_seconds=300,
        staleness_alert_seconds=1800,
        now=now,
    )


def test_run_once_syncs_all_sources() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    worker = _build_worker(store)
    asyncio.run(worker.run_once())
    assert store.get(_SID) is not None


def test_run_once_logs_error_on_stale_snapshot(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryReferenceDataSnapshotStore()
    stale_time = _NOW - timedelta(seconds=10_000)
    store.put(
        ReferenceDataSnapshot(
            source_id=_SID,
            rows=(tuple(_HEADER), tuple(_ROW)),
            content_hash="sha256:x",
            last_fetched_at=stale_time,
            content_updated_at=stale_time,
        )
    )
    provider = ReferenceDataProvider()

    class _FailingReader:
        def read_rows(self, source_id):
            raise RuntimeError("down")

    sync = SyncReferenceData(
        reader=_FailingReader(),
        store=store,
        provider=provider,
        source_ids=(_SID,),
        now=lambda: _NOW,
    )
    worker = ReferenceDataSyncWorker(
        sync=sync,
        store=store,
        sync_interval_seconds=300,
        staleness_alert_seconds=1800,
        now=lambda: _NOW,
    )
    with caplog.at_level(logging.ERROR):
        asyncio.run(worker.run_once())
    assert any(record.message == "reference_data_stale" for record in caplog.records)


def test_run_continues_after_tick_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryReferenceDataSnapshotStore()
    worker = ReferenceDataSyncWorker(
        sync=SyncReferenceData(
            reader=_Reader(),
            store=store,
            provider=ReferenceDataProvider(),
            source_ids=(_SID,),
            now=lambda: _NOW,
        ),
        store=store,
        sync_interval_seconds=0,
        staleness_alert_seconds=1800,
        now=lambda: _NOW,
    )
    stop = asyncio.Event()
    ticks = {"n": 0}

    async def flaky_run_once(self: ReferenceDataSyncWorker) -> None:
        ticks["n"] += 1
        if ticks["n"] == 1:
            raise ConnectionError("mongo blip")
        await asyncio.to_thread(self.sync.sync_all)
        self._check_staleness()
        stop.set()

    monkeypatch.setattr(ReferenceDataSyncWorker, "run_once", flaky_run_once)

    async def _scenario() -> None:
        await asyncio.wait_for(worker.run(stop), timeout=2.0)

    with caplog.at_level(logging.ERROR):
        asyncio.run(_scenario())

    assert ticks["n"] >= 2
    assert store.get(_SID) is not None
    assert any(record.message == "reference_data_sync_tick_failed" for record in caplog.records)
