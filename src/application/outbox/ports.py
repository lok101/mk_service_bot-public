from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

from src.domain.events import DomainEvent


@beartype
@dataclass(frozen=True, slots=True)
class FailedOutboxEntrySummary:
    entry_id: str
    event_id: str
    handler_id: str
    attempts: int
    last_error: str | None
    created_at: datetime


@runtime_checkable
class OutboxAdminStore(Protocol):
    @beartype
    def list_failed(
        self,
        *,
        handler_id: str | None = None,
        limit: int = 20,
    ) -> tuple[FailedOutboxEntrySummary, ...]: ...

    @beartype
    def count_failed(self, *, handler_id: str | None = None) -> int: ...

    @beartype
    def get_failed_entry(self, entry_id: str) -> FailedOutboxEntrySummary | None: ...

    @beartype
    def requeue_failed(self, entry_id: str) -> bool: ...


@runtime_checkable
class OutboxEventDeserializer(Protocol):
    @beartype
    def from_document(self, document: dict[str, Any]) -> DomainEvent: ...


@runtime_checkable
class OutboxTerminalFailureNotify(Protocol):
    @beartype
    async def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        event_document: dict[str, Any],
        error_message: str,
        entry_id: str | None = None,
        claim_id: str | None = None,
    ) -> None: ...
