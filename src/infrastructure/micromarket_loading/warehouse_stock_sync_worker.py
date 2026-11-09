from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.micromarket_loading.ports import MicromarketWarehouseStockSnapshotPort
from src.infrastructure.integrations.moysklad.exceptions import MoySkladError

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class WarehouseStockSyncRunner(Protocol):
    def sync_once(self) -> object: ...


@runtime_checkable
class WarehouseStockStalenessAlerter(Protocol):
    def alert_stale_snapshot(self, *, age_seconds: float) -> None: ...


@beartype
@dataclass(slots=True)
class MicromarketWarehouseStockSyncWorker:
    sync: WarehouseStockSyncRunner
    snapshot_store: MicromarketWarehouseStockSnapshotPort
    interval_seconds: int
    staleness_alert_seconds: int
    staleness_alert_cooldown_seconds: int = 900
    sync_failure_backoff_seconds: int = 0
    alerter: WarehouseStockStalenessAlerter | None = None
    _last_staleness_alert_at: datetime | None = field(
        default=None,
        init=False,
        compare=False,
        repr=False,
    )
    _pending_extra_sleep_seconds: float = field(
        default=0.0,
        init=False,
        compare=False,
        repr=False,
    )

    @beartype
    def run_once(self) -> None:
        try:
            self.sync.sync_once()
            self._pending_extra_sleep_seconds = 0.0
        except MoySkladError as error:
            self._pending_extra_sleep_seconds = float(self.sync_failure_backoff_seconds)
            _LOGGER.error(
                "micromarket_warehouse_stock_sync_tick_failed %s: %s",
                type(error).__name__,
                error,
            )
        except Exception:
            _LOGGER.exception("micromarket_warehouse_stock_sync_tick_failed")
        self._maybe_alert_staleness()

    @beartype
    def seconds_until_next_tick(self) -> float:
        return float(self.interval_seconds) + self._pending_extra_sleep_seconds

    @beartype
    def _maybe_alert_staleness(self) -> None:
        snapshot = self.snapshot_store.get()
        if snapshot is None:
            return
        age = (datetime.now(tz=UTC) - snapshot.refreshed_at.astimezone(UTC)).total_seconds()
        if age < self.staleness_alert_seconds:
            return
        _LOGGER.warning(
            "micromarket_warehouse_stock_snapshot_stale",
            extra={"age_seconds": age, "threshold": self.staleness_alert_seconds},
        )
        if self.alerter is None:
            return
        now = datetime.now(tz=UTC)
        last = self._last_staleness_alert_at
        if last is not None:
            since_last = (now - last.astimezone(UTC)).total_seconds()
            if since_last < self.staleness_alert_cooldown_seconds:
                return
        self._last_staleness_alert_at = now
        self.alerter.alert_stale_snapshot(age_seconds=age)

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.to_thread(self.run_once)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.seconds_until_next_tick())
