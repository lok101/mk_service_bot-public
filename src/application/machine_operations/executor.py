from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from beartype import beartype

from src.application.machine_operations.errors import MachineOperationsConcurrencyError
from src.application.machine_operations.ports import (
    DomainEventPublisher,
    MachineOperationsRepository,
    TechnicianLastMaintenanceProjection,
)
from src.domain.events import DomainEvent
from src.domain.ids import MachineId
from src.domain.machine_operations import MachineOperations
from src.domain.machine_operations.events import (
    MaintenanceCompleted,
    PhotosSubmitted,
    maintenance_completed_at_from_event,
)
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot

DEFAULT_MAX_SAVE_RETRIES = 5

T = TypeVar("T")


@beartype
def _publish_new_events(
    publisher: DomainEventPublisher | None,
    pending_events: list[DomainEvent],
) -> None:
    if publisher is None:
        return

    for event in pending_events:
        publisher.publish(event)


@beartype
@dataclass(frozen=True, slots=True)
class MachineOperationsExecutor:
    repository: MachineOperationsRepository
    publisher: DomainEventPublisher | None = None
    technician_last_maintenance: TechnicianLastMaintenanceProjection | None = None
    max_save_retries: int = DEFAULT_MAX_SAVE_RETRIES

    def __post_init__(self) -> None:
        if self.max_save_retries < 1:
            raise ValueError("max_save_retries must be at least 1")

    @beartype
    def execute(
        self,
        machine_id: MachineId,
        command_fn: Callable[[MachineOperations], T],
    ) -> T:
        last_error: MachineOperationsConcurrencyError | None = None

        for _attempt in range(self.max_save_retries):
            aggregate = self.repository.get(machine_id)
            result = command_fn(aggregate)
            pending_events = aggregate.collect_events()
            if not pending_events:
                # Idempotent re-submit: the aggregate returned an already-recorded event
                # without appending new ones. Re-publish it so at-least-once delivery still
                # enqueues the outbox task if a prior publish was lost; the outbox dedupes
                # on (event_id, handler_id).
                if isinstance(result, DomainEvent):
                    _publish_new_events(self.publisher, [result])
                return result

            try:
                self.repository.save(aggregate)
            except MachineOperationsConcurrencyError as error:
                last_error = error
                continue

            _publish_new_events(self.publisher, pending_events)
            if self.technician_last_maintenance is not None:
                for event in pending_events:
                    if not isinstance(event, (MaintenanceCompleted, PhotosSubmitted)):
                        continue
                    completed_at = maintenance_completed_at_from_event(event)
                    if completed_at is None:
                        continue
                    self.technician_last_maintenance.upsert(
                        TechnicianLastMaintenanceSnapshot(
                            technician_id=event.technician_id,
                            machine_id=event.machine_id,
                            completed_at=completed_at,
                        ),
                    )
            aggregate.clear_pending_events()
            return result

        assert last_error is not None
        raise last_error
