from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from beartype import beartype

from src.application.technician_settlement.errors import TechnicianSettlementConcurrencyError
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.domain.ids import TechnicianId
from src.domain.technician_settlement import TechnicianSettlement

DEFAULT_MAX_SAVE_RETRIES = 5

T = TypeVar("T")


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianSettlementExecutor:
    repository: TechnicianSettlementRepository
    max_save_retries: int = DEFAULT_MAX_SAVE_RETRIES

    def __post_init__(self) -> None:
        if self.max_save_retries < 1:
            raise ValueError("max_save_retries must be at least 1")

    @beartype
    def execute(
        self,
        technician_id: TechnicianId,
        command_fn: Callable[[TechnicianSettlement], T],
    ) -> T:
        last_error: TechnicianSettlementConcurrencyError | None = None

        for _attempt in range(self.max_save_retries):
            aggregate = self.repository.get(technician_id)
            result = command_fn(aggregate)
            pending_events = aggregate.collect_events()
            if not pending_events:
                return result

            try:
                self.repository.save(aggregate)
            except TechnicianSettlementConcurrencyError as error:
                last_error = error
                continue

            aggregate.clear_pending_events()
            return result

        assert last_error is not None
        raise last_error
