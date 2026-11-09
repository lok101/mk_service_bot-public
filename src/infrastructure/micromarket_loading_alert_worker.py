from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from beartype import beartype

from src.application.micromarket_loading.alert_sweep import SweepMicromarketLoadingAlerts

_LOGGER: Final = logging.getLogger(__name__)
SWEEP_INTERVAL_SECONDS: Final = 60 * 60


@beartype
@dataclass(slots=True)
class MicromarketLoadingAlertWorker:
    sweep: SweepMicromarketLoadingAlerts

    @beartype
    async def sweep_once(self) -> None:
        now = datetime.now(tz=UTC)
        await asyncio.to_thread(self.sweep.sweep_once, now)

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.sweep_once()
            except Exception:
                _LOGGER.exception("micromarket_loading_alert_sweep_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=SWEEP_INTERVAL_SECONDS)


__all__ = ["SWEEP_INTERVAL_SECONDS", "MicromarketLoadingAlertWorker"]
