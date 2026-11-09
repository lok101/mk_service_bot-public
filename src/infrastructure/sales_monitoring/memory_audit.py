from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from beartype import beartype

from src.application.sales_monitoring.no_sales_control import control_blocks_technician_visit
from src.domain.events import DomainEvent
from src.domain.ids import MachineId
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
)
from src.infrastructure.mongodb.sales_monitoring_audit_documents import (
    build_audit_document,
    document_from_no_sales_episode,
    document_from_no_sales_episode_opened,
    no_sales_audit_document_id,
    offline_audit_document_id,
)

_NO_SALES_CONTROL_KINDS = frozenset(
    {"no_sales_mute", "no_sales_mute_cancel", "no_sales_engineer_wait"},
)


@beartype
@dataclass
class InMemorySalesMonitoringAuditStore:
    _documents: dict[str, dict[str, Any]] = field(default_factory=dict)

    @beartype
    def upsert_from_event(self, event: DomainEvent) -> None:
        existing = None
        if isinstance(event, SalesMonitoringOfflineCleared):
            existing = self._documents.get(offline_audit_document_id(event.machine_id))
        elif isinstance(event, SalesMonitoringNoSalesStaleCleared):
            existing = self._documents.get(no_sales_audit_document_id(event.machine_id))
        document = build_audit_document(event, existing=existing)
        self._documents[str(document["_id"])] = document
        if isinstance(event, SalesMonitoringNoSalesStaleOpened):
            episode = document_from_no_sales_episode_opened(event)
            existing_episode = self._documents.get(str(episode["_id"]))
            if existing_episode is not None and existing_episode.get("cleared_at") is not None:
                return
            self._documents[str(episode["_id"])] = episode
        elif isinstance(event, SalesMonitoringNoSalesStaleCleared):
            episode = document_from_no_sales_episode(event)
            self._documents[str(episode["_id"])] = episode

    @beartype
    def upsert_control(self, document: dict[str, object]) -> None:
        document_id = document["_id"]
        self._documents[str(document_id)] = dict(document)

    @beartype
    def upsert_audit_document(self, document: dict[str, object]) -> None:
        """Upsert any audit document by `_id` without sticky/episode event side effects."""
        document_id = document["_id"]
        self._documents[str(document_id)] = dict(document)

    @beartype
    def list_no_sales_controls(self, machine_id: MachineId) -> list[dict[str, object]]:
        machine_value = machine_id.value
        return [
            dict(document)
            for document in self._documents.values()
            if document.get("kind") in _NO_SALES_CONTROL_KINDS
            and document.get("machine_id") == machine_value
        ]

    @beartype
    def blocks_technician_visit(self, *, machine_id: MachineId, opened_event_id: str) -> bool:
        return control_blocks_technician_visit(
            self.list_no_sales_controls(machine_id),
            machine_id=machine_id,
            opened_event_id=opened_event_id,
        )

    @beartype
    def list_open_offline(self) -> list[dict[str, object]]:
        return [
            dict(document)
            for document in self._documents.values()
            if document.get("kind") == "offline" and document.get("status") == "open"
        ]

    @beartype
    def list_open_no_sales(self) -> list[dict[str, object]]:
        return [
            dict(document)
            for document in self._documents.values()
            if document.get("kind") == "no_sales" and document.get("status") == "open"
        ]

    @beartype
    def list_cleared_no_sales_since(self, *, cleared_at_gte: datetime) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for document in self._documents.values():
            if document.get("kind") != "no_sales":
                continue
            if document.get("status") != "cleared":
                continue
            cleared_at = document.get("cleared_at")
            if not isinstance(cleared_at, datetime):
                continue
            if cleared_at >= cleared_at_gte:
                result.append(dict(document))
        return result

    @beartype
    def list_no_sales_episodes_overlapping(
        self, *, start: datetime, end: datetime
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for document in self._documents.values():
            if document.get("kind") != "no_sales_episode":
                continue
            opened_at = document.get("opened_at")
            cleared_at = document.get("cleared_at")
            opened_in = isinstance(opened_at, datetime) and start <= opened_at <= end
            cleared_in = isinstance(cleared_at, datetime) and start <= cleared_at <= end
            if opened_in or cleared_in:
                result.append(dict(document))
        return result

    @beartype
    def get(self, document_id: str) -> dict[str, object] | None:
        document = self._documents.get(document_id)
        return dict(document) if document is not None else None
