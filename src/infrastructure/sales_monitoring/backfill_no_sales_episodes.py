from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

from src.domain.events import DomainEvent
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
)
from src.infrastructure.mongodb.sales_monitoring_audit_documents import (
    document_from_no_sales_episode,
    document_from_no_sales_episode_opened,
)

NoSalesBackfillEvent = SalesMonitoringNoSalesStaleOpened | SalesMonitoringNoSalesStaleCleared


@runtime_checkable
class EpisodeAuditDocumentStore(Protocol):
    @beartype
    def upsert_audit_document(self, document: dict[str, object]) -> None: ...


@beartype
def build_episode_documents(events: Sequence[DomainEvent]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, NoSalesBackfillEvent]] = {}
    for event in events:
        if isinstance(event, SalesMonitoringNoSalesStaleOpened):
            key = event.event_id.value
            groups.setdefault(key, {})["opened"] = event
        elif isinstance(event, SalesMonitoringNoSalesStaleCleared):
            key = event.opened_event_id.value
            groups.setdefault(key, {})["cleared"] = event

    documents: list[dict[str, Any]] = []
    for group in groups.values():
        opened = group.get("opened")
        cleared = group.get("cleared")
        if isinstance(opened, SalesMonitoringNoSalesStaleOpened):
            document = document_from_no_sales_episode_opened(opened)
            if isinstance(cleared, SalesMonitoringNoSalesStaleCleared):
                document = {
                    **document,
                    **document_from_no_sales_episode(cleared),
                }
            documents.append(document)
        elif isinstance(cleared, SalesMonitoringNoSalesStaleCleared):
            documents.append(document_from_no_sales_episode(cleared))
    return documents


@beartype
def run_backfill(
    *,
    events: Sequence[DomainEvent],
    audit_store: EpisodeAuditDocumentStore,
    dry_run: bool,
) -> int:
    documents = build_episode_documents(events)
    if dry_run:
        return len(documents)
    for document in documents:
        audit_store.upsert_audit_document(dict(document))
    return len(documents)
