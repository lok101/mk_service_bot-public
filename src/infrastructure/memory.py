from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations import MachineOperationsConcurrencyError
from src.application.machine_operations.ports import (
    EventStore,
    MachineOperationsRepository,
)
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.events import DomainEvent
from src.domain.ids import MachineId
from src.domain.machine_operations import MachineOperations
from src.domain.machine_operations.events import MaintenanceCompleted, PhotosSubmitted
from src.infrastructure.mongodb.errors import EventStoreConcurrencyError


@beartype
@dataclass(frozen=True, slots=True)
class InMemoryEventStore(EventStore):
    events: list[DomainEvent] = field(default_factory=list)
    _aggregate_versions: dict[str, int] = field(default_factory=dict)

    @beartype
    def append(self, event: DomainEvent, *, expected_version: int) -> None:
        if expected_version < 0:
            raise ValueError("expected_version must be non-negative")
        if any(existing.event_id == event.event_id for existing in self.events):
            return
        machine_id = getattr(event, "machine_id", None)
        aggregate_id = machine_id.value if machine_id is not None else ""
        current_version = self._aggregate_versions.get(aggregate_id, 0)
        if expected_version != current_version:
            raise EventStoreConcurrencyError(
                f"Expected version {expected_version} for aggregate {aggregate_id!r}, "
                f"current is {current_version}",
            )
        self.events.append(event)
        self._aggregate_versions[aggregate_id] = expected_version + 1

    @beartype
    def get_events_for_machine(self, machine_id: MachineId) -> list[DomainEvent]:
        return [event for event in self.events if getattr(event, "machine_id", None) == machine_id]

    @beartype
    def list_maintenance_completed_in_completed_at_window(
        self,
        machine_id: MachineId,
        *,
        completed_at_start_inclusive: datetime,
        completed_at_end_exclusive: datetime,
    ) -> tuple[MaintenanceCompleted, ...]:
        matched: list[MaintenanceCompleted] = []
        start = completed_at_start_inclusive.astimezone(UTC)
        end = completed_at_end_exclusive.astimezone(UTC)
        for event in self.events:
            if getattr(event, "machine_id", None) != machine_id:
                continue
            if isinstance(event, MaintenanceCompleted):
                completed_at = event.completed_at.astimezone(UTC)
                if completed_at < start or completed_at >= end:
                    continue
                matched.append(event)
                continue
            if isinstance(event, PhotosSubmitted):
                if event.maintenance_completed_at is None:
                    continue
                completed_at = event.maintenance_completed_at.astimezone(UTC)
                if completed_at < start or completed_at >= end:
                    continue
                matched.append(
                    MaintenanceCompleted(
                        event_id=event.event_id,
                        technician_id=event.technician_id,
                        machine_id=event.machine_id,
                        completed_at=event.maintenance_completed_at,
                        occurred_at=event.occurred_at,
                    ),
                )
        matched.sort(key=lambda item: (item.completed_at, item.event_id.value))
        return tuple(matched)


@beartype
@dataclass(frozen=True, slots=True)
class EventSourcedMachineOperationsRepository(MachineOperationsRepository):
    event_store: EventStore
    revision_interval_min_days: int | None = field(default=None)
    revision_interval_max_days: int | None = field(default=None)
    service_calendar_timezone: ZoneInfo = field(
        default=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
    )
    service_day_end_hour: int = field(default=6)

    @beartype
    def get(self, machine_id: MachineId) -> MachineOperations:
        events = self.event_store.get_events_for_machine(machine_id)
        return MachineOperations.rehydrate(
            machine_id,
            events,
            revision_interval_min_days=self.revision_interval_min_days,
            revision_interval_max_days=self.revision_interval_max_days,
            service_calendar_timezone=self.service_calendar_timezone,
            service_day_end_hour=self.service_day_end_hour,
            loaded_version=len(events),
        )

    @beartype
    def save(self, aggregate: MachineOperations) -> None:
        pending = aggregate.collect_events()
        if len(pending) > 1:
            raise ValueError("one event per save boundary")
        if not pending:
            return
        try:
            self.event_store.append(
                pending[0],
                expected_version=aggregate.loaded_version,
            )
        except EventStoreConcurrencyError as error:
            raise MachineOperationsConcurrencyError(str(error)) from error
