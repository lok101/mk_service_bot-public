from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from beartype import beartype

from src.application.form_submissions import (
    DeferredRetryOutboxError,
    NonRetryableOutboxError,
)
from src.application.machine_operations.ports import OutboxStore
from src.application.outbox.logging import outbox_log_extra
from src.application.outbox.ports import OutboxTerminalFailureNotify
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.serialization import event_from_outbox_document

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 10
DEFAULT_HANDLER_WARNING_SECONDS = 10.0


@beartype
@dataclass(frozen=True, slots=True)
class OutboxWorker:
    store: OutboxStore
    processors: OutboxProcessorRegistry
    poll_interval_seconds: float = 1.0
    batch_size: int = DEFAULT_BATCH_SIZE
    handler_warning_seconds: float = DEFAULT_HANDLER_WARNING_SECONDS
    failure_notifier: OutboxTerminalFailureNotify | None = None

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if self.handler_warning_seconds <= 0:
            raise ValueError("handler_warning_seconds must be positive")

    @beartype
    async def run_forever(self) -> None:
        while True:
            await self.process_batch()
            await asyncio.sleep(self.poll_interval_seconds)

    @beartype
    async def run_until_shutdown(self, shutdown: asyncio.Event) -> None:
        # Single-replica assumption: in-flight entries are not drained on shutdown.
        # Mongo lease reclaim (~300s) returns stuck processing. See operational-assumptions.md.
        while not shutdown.is_set():
            await self.process_batch()
            try:
                await asyncio.wait_for(
                    shutdown.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except TimeoutError:
                continue

    @beartype
    async def process_batch(self, *, handler_id: str | None = None) -> int:
        return await self._claim_and_process(handler_id=handler_id, limit=self.batch_size)

    @beartype
    async def process_batch_for_handler(self, handler_id: str, *, limit: int | None = None) -> int:
        batch_limit = self.batch_size if limit is None else limit
        return await self._claim_and_process(handler_id=handler_id, limit=batch_limit)

    @beartype
    async def _claim_and_process(self, *, handler_id: str | None, limit: int) -> int:
        await asyncio.to_thread(self.store.reclaim_stuck_processing)
        if handler_id is None:
            entries = await asyncio.to_thread(
                self.store.claim_pending,
                limit=limit,
                handler_id=None,
                handler_ids=self.processors.registered_handler_ids(),
            )
        else:
            entries = await asyncio.to_thread(
                self.store.claim_pending,
                limit=limit,
                handler_id=handler_id,
            )
        for entry in entries:
            await self._process_entry(entry)
        return len(entries)

    @beartype
    async def _process_entry(self, entry: dict[str, object]) -> None:
        entry_id = entry.get("entry_id")
        handler_id = entry.get("handler_id")
        event_document = entry.get("event_document")
        claim_id = entry.get("claim_id")
        if (
            not isinstance(entry_id, str)
            or not isinstance(handler_id, str)
            or not isinstance(event_document, dict)
            or not isinstance(claim_id, str)
        ):
            invalid_shape_extra = outbox_log_extra(
                entry_id=entry_id if isinstance(entry_id, str) else None,
                handler_id=handler_id if isinstance(handler_id, str) else None,
                claim_id=claim_id if isinstance(claim_id, str) else None,
            )
            logger.error(
                "Outbox entry has invalid shape: %r",
                entry,
                extra=invalid_shape_extra,
            )
            if isinstance(entry_id, str) and isinstance(claim_id, str):
                error_message = "Outbox entry has invalid shape"
                terminal = await asyncio.to_thread(
                    self.store.mark_failed,
                    entry_id,
                    claim_id=claim_id,
                    error_message=error_message,
                    permanent=True,
                )
                if not terminal:
                    logger.warning(
                        "Outbox entry %s lease was lost before marking invalid shape as failed",
                        entry_id,
                        extra=invalid_shape_extra,
                    )
            return

        event_id_str = event_document.get("event_id")
        event_id_for_log = event_id_str if isinstance(event_id_str, str) else None
        log_extra = outbox_log_extra(
            entry_id=entry_id,
            handler_id=handler_id,
            event_id=event_id_for_log,
            claim_id=claim_id,
        )

        try:
            event = event_from_outbox_document(event_document)
            started_at = time.monotonic()
            await self.processors.process(handler_id, event)
            elapsed_seconds = time.monotonic() - started_at
            if elapsed_seconds >= self.handler_warning_seconds:
                logger.warning(
                    "Outbox handler %s for entry %s took %.2fs",
                    handler_id,
                    entry_id,
                    elapsed_seconds,
                    extra=log_extra,
                )
        except DeferredRetryOutboxError as error:
            logger.warning(
                "Outbox handler %s deferred retry for entry %s: %s",
                handler_id,
                entry_id,
                error,
                extra=log_extra,
            )
            terminal = await asyncio.to_thread(
                self.store.mark_failed,
                entry_id,
                claim_id=claim_id,
                error_message=str(error),
                retry_delay=error.delay,
                max_attempts_override=error.max_attempts,
            )
            if terminal:
                await self._notify_terminal_failure(
                    handler_id=handler_id,
                    event_document=event_document,
                    error_message=str(error),
                    entry_id=entry_id,
                    claim_id=claim_id,
                )
            return
        except NonRetryableOutboxError as error:
            logger.error(
                "Outbox handler %s permanent failure for entry %s: %s",
                handler_id,
                entry_id,
                error,
                extra=log_extra,
            )
            terminal = await asyncio.to_thread(
                self.store.mark_failed,
                entry_id,
                claim_id=claim_id,
                error_message=str(error),
                permanent=True,
            )
            if terminal:
                await self._notify_terminal_failure(
                    handler_id=handler_id,
                    event_document=event_document,
                    error_message=str(error),
                    entry_id=entry_id,
                    claim_id=claim_id,
                )
            return
        except Exception as error:
            terminal = await asyncio.to_thread(
                self.store.mark_failed,
                entry_id,
                claim_id=claim_id,
                error_message=str(error),
            )
            if terminal:
                logger.exception(
                    "Outbox handler %s failed for entry %s",
                    handler_id,
                    entry_id,
                    extra=log_extra,
                )
                await self._notify_terminal_failure(
                    handler_id=handler_id,
                    event_document=event_document,
                    error_message=str(error),
                    entry_id=entry_id,
                    claim_id=claim_id,
                )
            else:
                logger.warning(
                    "Outbox handler %s failed for entry %s",
                    handler_id,
                    entry_id,
                    exc_info=True,
                    extra=log_extra,
                )
            return

        processed = await asyncio.to_thread(
            self.store.mark_processed,
            entry_id,
            claim_id=claim_id,
        )
        if not processed:
            logger.warning(
                "Outbox entry %s lease was lost before mark_processed",
                entry_id,
                extra=log_extra,
            )

    @beartype
    async def _notify_terminal_failure(
        self,
        *,
        handler_id: str,
        event_document: dict[str, Any],
        error_message: str,
        entry_id: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        if self.failure_notifier is None:
            return

        try:
            await self.failure_notifier.notify_terminal_failure(
                handler_id=handler_id,
                event_document=event_document,
                error_message=error_message,
                entry_id=entry_id,
                claim_id=claim_id,
            )
        except Exception:
            logger.exception(
                "Failed to notify technician about outbox failure for handler %s",
                handler_id,
            )
