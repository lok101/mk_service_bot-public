from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class ProductCatalogMsSyncRunner(Protocol):
    async def sync_once(self) -> None: ...


@beartype
@dataclass(slots=True)
class ProductCatalogMsSyncWorker:
    sync: ProductCatalogMsSyncRunner
    interval_seconds: int

    @beartype
    async def run_once(self) -> None:
        await self.sync.sync_once()

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception:
                _LOGGER.exception("product_catalog_ms_sync_tick_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
