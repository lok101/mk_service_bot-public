from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.infrastructure.micromarket_loading.warehouse_stock_sync_worker import (
    MicromarketWarehouseStockSyncWorker,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketWarehouseStockSnapshotStore,
)

_WAREHOUSE = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


class _RecordingAlerter:
    def __init__(self) -> None:
        self.ages: list[float] = []

    def alert_stale_snapshot(self, *, age_seconds: float) -> None:
        self.ages.append(age_seconds)


class _OkSync:
    def sync_once(self) -> object:
        return None


class _BoomSync:
    def sync_once(self) -> object:
        raise RuntimeError("ms down")


class _MoySkladFailSync:
    def sync_once(self) -> object:
        from src.infrastructure.integrations.moysklad.exceptions import MoySkladAPIError

        raise MoySkladAPIError("MoySklad HTTP 500: invalid JSON body")


def test_worker_alerts_when_snapshot_stale() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE,
            refreshed_at=datetime.now(tz=UTC) - timedelta(seconds=200),
            qty_by_catalog_code={"SKU-1": Decimal("1")},
        ),
    )
    alerter = _RecordingAlerter()
    MicromarketWarehouseStockSyncWorker(
        sync=_OkSync(),
        snapshot_store=store,
        interval_seconds=60,
        staleness_alert_seconds=120,
        alerter=alerter,
    ).run_once()
    assert len(alerter.ages) == 1
    assert alerter.ages[0] >= 200


def test_worker_skips_alert_when_fresh() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE,
            refreshed_at=datetime.now(tz=UTC) - timedelta(seconds=30),
            qty_by_catalog_code={"SKU-1": Decimal("1")},
        ),
    )
    alerter = _RecordingAlerter()
    MicromarketWarehouseStockSyncWorker(
        sync=_OkSync(),
        snapshot_store=store,
        interval_seconds=60,
        staleness_alert_seconds=120,
        alerter=alerter,
    ).run_once()
    assert alerter.ages == []


def test_worker_throttles_stale_telegram_alerts() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE,
            refreshed_at=datetime.now(tz=UTC) - timedelta(seconds=200),
            qty_by_catalog_code={"SKU-1": Decimal("1")},
        ),
    )
    alerter = _RecordingAlerter()
    worker = MicromarketWarehouseStockSyncWorker(
        sync=_OkSync(),
        snapshot_store=store,
        interval_seconds=60,
        staleness_alert_seconds=120,
        staleness_alert_cooldown_seconds=3600,
        alerter=alerter,
    )
    worker.run_once()
    worker.run_once()
    assert len(alerter.ages) == 1


def test_worker_logs_moysklad_errors_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    MicromarketWarehouseStockSyncWorker(
        sync=_MoySkladFailSync(),
        snapshot_store=InMemoryMicromarketWarehouseStockSnapshotStore(),
        interval_seconds=60,
        staleness_alert_seconds=120,
    ).run_once()
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is None
    assert "MoySkladAPIError" in caplog.records[0].message


def test_worker_extends_next_sleep_after_moysklad_error() -> None:
    worker = MicromarketWarehouseStockSyncWorker(
        sync=_MoySkladFailSync(),
        snapshot_store=InMemoryMicromarketWarehouseStockSnapshotStore(),
        interval_seconds=60,
        staleness_alert_seconds=120,
        sync_failure_backoff_seconds=90,
    )
    assert worker.seconds_until_next_tick() == 60.0
    worker.run_once()
    assert worker.seconds_until_next_tick() == 150.0


def test_worker_resets_backoff_after_successful_tick() -> None:
    worker = MicromarketWarehouseStockSyncWorker(
        sync=_MoySkladFailSync(),
        snapshot_store=InMemoryMicromarketWarehouseStockSnapshotStore(),
        interval_seconds=60,
        staleness_alert_seconds=120,
        sync_failure_backoff_seconds=90,
    )
    worker.run_once()
    worker.sync = _OkSync()  # type: ignore[method-assign]
    worker.run_once()
    assert worker.seconds_until_next_tick() == 60.0


def test_worker_keeps_prior_snapshot_when_sync_fails() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE,
            refreshed_at=datetime.now(tz=UTC),
            qty_by_catalog_code={"SKU-1": Decimal("9")},
        ),
    )
    MicromarketWarehouseStockSyncWorker(
        sync=_BoomSync(),
        snapshot_store=store,
        interval_seconds=60,
        staleness_alert_seconds=120,
    ).run_once()
    got = store.get()
    assert got is not None
    assert got.qty_by_catalog_code["SKU-1"] == Decimal("9")
