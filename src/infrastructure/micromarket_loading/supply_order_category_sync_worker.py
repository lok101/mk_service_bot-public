from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.infrastructure.integrations.moysklad.exceptions import MoySkladError

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class CategoryFactsSyncRunner(Protocol):
    def sync_once(self) -> object: ...


@beartype
@dataclass(slots=True)
class SupplyOrderCategoryFactsSyncWorker:
    sync: CategoryFactsSyncRunner
    interval_seconds: int

    @beartype
    def run_once(self) -> None:
        try:
            self.sync.sync_once()
        except MoySkladError as error:
            _LOGGER.error(
                "supply_order_category_facts_sync_tick_failed %s: %s",
                type(error).__name__,
                error,
            )
        except Exception:
            _LOGGER.exception("supply_order_category_facts_sync_tick_failed")

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.to_thread(self.run_once)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=float(self.interval_seconds))
