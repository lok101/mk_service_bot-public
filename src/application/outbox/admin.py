from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.outbox.ports import FailedOutboxEntrySummary, OutboxAdminStore


class RequeueFailedOutboxEntryError(ValueError):
    """Raised when an outbox entry cannot be requeued."""


@beartype
@dataclass(frozen=True, slots=True)
class ListFailedOutboxEntriesQuery:
    handler_id: str | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")


@beartype
@dataclass(frozen=True, slots=True)
class ListFailedOutboxEntriesService:
    store: OutboxAdminStore

    @beartype
    def execute(
        self,
        query: ListFailedOutboxEntriesQuery,
    ) -> tuple[FailedOutboxEntrySummary, ...]:
        return self.store.list_failed(
            handler_id=query.handler_id,
            limit=query.limit,
        )


@beartype
@dataclass(frozen=True, slots=True)
class GetFailedOutboxEntryService:
    store: OutboxAdminStore

    @beartype
    def execute(self, entry_id: str) -> FailedOutboxEntrySummary | None:
        stripped = entry_id.strip()
        if not stripped:
            return None
        return self.store.get_failed_entry(stripped)


@beartype
@dataclass(frozen=True, slots=True)
class RequeueFailedOutboxEntryService:
    store: OutboxAdminStore

    @beartype
    def execute(self, entry_id: str) -> None:
        if not entry_id.strip():
            raise RequeueFailedOutboxEntryError("entry_id must not be empty")
        if not self.store.requeue_failed(entry_id.strip()):
            raise RequeueFailedOutboxEntryError(
                f"Outbox entry {entry_id!r} not found or not in failed status",
            )
