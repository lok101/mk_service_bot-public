from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.reference_data.ports import ReferenceDataSnapshotStore
from src.application.reference_data.staleness import evaluate_staleness
from src.application.reference_data.sync import SyncReferenceData

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
@dataclass(slots=True)
class ReferenceDataSyncWorker:
    sync: SyncReferenceData
    store: ReferenceDataSnapshotStore
    sync_interval_seconds: int
    staleness_alert_seconds: int
    now: Callable[[], datetime] = _utc_now

    @beartype
    async def run_once(self) -> None:
        await asyncio.to_thread(self.sync.sync_all)
        self._check_staleness()

    @beartype
    def _check_staleness(self) -> None:
        moment = self.now()
        for source_id in self.sync.source_ids:
            snapshot = self.store.get(source_id)
            if evaluate_staleness(
                snapshot,
                now=moment,
                threshold_seconds=self.staleness_alert_seconds,
            ):
                _LOGGER.error(
                    "reference_data_stale",
                    extra={"source_id": source_id.value},
                )

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception:
                _LOGGER.exception("reference_data_sync_tick_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.sync_interval_seconds)
