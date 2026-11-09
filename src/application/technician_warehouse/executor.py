from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from beartype import beartype

from src.application.technician_warehouse.errors import TechnicianWarehouseConcurrencyError
from src.application.technician_warehouse.ports import (
    DomainEventPublisher,
    TechnicianWarehouseRepository,
)
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse import TechnicianWarehouse
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseInventoryCounted,
    WarehouseEvent,
)

T = TypeVar("T")


@beartype
def _publish_inventory_events(
    publisher: DomainEventPublisher | None,
    events: Sequence[WarehouseEvent],
) -> None:
    if publisher is None:
        return
    for event in events:
        if isinstance(event, TechnicianWarehouseInventoryCounted):
            publisher.publish(event)


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseExecutor:
    repository: TechnicianWarehouseRepository
    publisher: DomainEventPublisher | None = None
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    @beartype
    def execute(
        self,
        technician_id: TechnicianId,
        command: Callable[[TechnicianWarehouse], T],
    ) -> T:
        for attempt in range(self.max_attempts):
            aggregate = self.repository.get(technician_id)
            expected_version = aggregate.version
            result = command(aggregate)
            pending_events = aggregate.collect_events()
            if not pending_events:
                if isinstance(result, TechnicianWarehouseInventoryCounted):
                    _publish_inventory_events(self.publisher, [result])
                return result
            try:
                self.repository.save(aggregate, expected_version=expected_version)
            except TechnicianWarehouseConcurrencyError:
                if attempt + 1 == self.max_attempts:
                    raise
                continue
            _publish_inventory_events(self.publisher, list(pending_events))
            return result
        raise AssertionError("unreachable")
