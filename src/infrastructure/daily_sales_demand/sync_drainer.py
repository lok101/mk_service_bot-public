from __future__ import annotations

import asyncio
from dataclasses import dataclass

from beartype import beartype

from src.infrastructure.outbox.worker import OutboxWorker


@beartype
@dataclass(frozen=True, slots=True)
class SyncOutboxHandlerDrainer:
    """Thin sync adapter around OutboxWorker.process_batch_for_handler (SM twin)."""

    worker: OutboxWorker

    @beartype
    def drain_handler(self, handler_id: str) -> int:
        return asyncio.run(self.worker.process_batch_for_handler(handler_id))
