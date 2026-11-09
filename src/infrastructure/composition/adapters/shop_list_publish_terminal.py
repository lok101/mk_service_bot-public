from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from beartype import beartype

from src.application.micromarket_loading import mark_shop_list_publication_failed
from src.application.micromarket_loading.ports import (
    MicromarketPlanogramStore,
    ShopListPublishJournal,
)
from src.application.outbox.handler_ids import MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID
from src.application.outbox.ports import OutboxTerminalFailureNotify


@beartype
@dataclass(frozen=True, slots=True)
class ShopListPublishTerminalNotifier:
    inner: OutboxTerminalFailureNotify
    store: MicromarketPlanogramStore
    journal: ShopListPublishJournal | None = None
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)

    @beartype
    async def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        event_document: dict[str, Any],
        error_message: str,
        entry_id: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        await self.inner.notify_terminal_failure(
            handler_id=handler_id,
            event_document=event_document,
            error_message=error_message,
            entry_id=entry_id,
            claim_id=claim_id,
        )
        if handler_id != MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID:
            return
        publication_id = str(event_document["event_id"])
        payload = event_document.get("payload")
        machine_code: str | None = None
        if isinstance(payload, dict):
            raw = payload.get("machine_code")
            if isinstance(raw, str):
                machine_code = raw
        mark_shop_list_publication_failed(
            self.store,
            publication_id,
            error_message,
            machine_code=machine_code,
            journal=self.journal,
            now=self.now_factory(),
        )
