from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.product_identity.sync_procurement_mirror import (
    ProcurementMirrorSyncStats,
)

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class ProcurementMirrorSyncRunner(Protocol):
    def sync_all(self) -> ProcurementMirrorSyncStats: ...


@beartype
@dataclass(slots=True)
class ProductProcurementMirrorSyncWorker:
    sync: ProcurementMirrorSyncRunner
    interval_seconds: int

    @beartype
    async def run_once(self) -> None:
        # Sync is sync+HTTP-heavy; keep the app event loop free for health/admin.
        await asyncio.to_thread(self.sync.sync_all)

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception:
                _LOGGER.exception("product_procurement_mirror_sync_tick_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
