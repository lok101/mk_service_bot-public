from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

_LOGGER = logging.getLogger(__name__)
_HEARTBEAT_INTERVAL_SECONDS = 60.0


@runtime_checkable
class EffectsWorkerStatusCollection(Protocol):
    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...


@beartype
def _utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@beartype
def record_effects_worker_heartbeat(
    collection: EffectsWorkerStatusCollection,
    *,
    at: str,
) -> None:
    collection.update_one(
        {"_id": "worker"},
        {"$set": {"last_heartbeat_at": at, "worker_enabled": True}},
        upsert=True,
    )


@beartype
async def effects_worker_heartbeat_loop(
    collection: EffectsWorkerStatusCollection | None,
    shutdown: asyncio.Event,
    *,
    interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
    now: Callable[[], str] | None = None,
) -> None:
    if collection is None:
        await shutdown.wait()
        return
    clock = _utc_iso if now is None else now
    while not shutdown.is_set():
        try:
            await asyncio.to_thread(record_effects_worker_heartbeat, collection, at=clock())
        except Exception:
            _LOGGER.exception("effects_worker_heartbeat_failed")
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
