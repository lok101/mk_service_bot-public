from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.domain.form_submission import FrozenInventoryLine
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.quantities import packages_to_base_quantity
from src.domain.technician_warehouse.events import TechnicianWarehouseLoadingObserved
from src.domain.technician_warehouse.models import TechnicianWarehouseLine

_LOGGER = logging.getLogger(__name__)


@beartype
def _normalize_loading_lines(
    lines: tuple[FrozenInventoryLine, ...],
) -> tuple[TechnicianWarehouseLine, ...]:
    normalized: list[TechnicianWarehouseLine] = []
    for line in lines:
        pack_size = line.product_spec.pack_size
        if pack_size is None:
            _LOGGER.warning(
                "skip loading line without pack_size product_code=%s",
                line.product_spec.product_code,
            )
            continue
        quantity_base = packages_to_base_quantity(
            packages=line.quantity,
            pack_size=pack_size,
        )
        if quantity_base <= 0:
            continue
        normalized.append(
            TechnicianWarehouseLine(
                sku=line.product_spec.product_code,
                quantity_base=quantity_base,
            )
        )
    return tuple(normalized)


@beartype
@dataclass(slots=True)
class ObserveTechnicianWarehouseLoading:
    executor: TechnicianWarehouseExecutor

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
        source_event_id: str,
        machine_id: MachineId,
        submitted_at: datetime,
        lines: tuple[FrozenInventoryLine, ...],
    ) -> TechnicianWarehouseLoadingObserved | None:
        normalized = _normalize_loading_lines(lines)
        if not normalized:
            return None

        return self.executor.execute(
            technician_id,
            lambda warehouse: warehouse.observe_loading(
                TechnicianWarehouseLoadingObserved(
                    event_id=EventId(str(uuid.uuid4())),
                    technician_id=technician_id,
                    occurred_at=datetime.now(tz=UTC),
                    source_event_id=source_event_id,
                    machine_id=machine_id,
                    submitted_at=submitted_at,
                    lines=normalized,
                )
            ),
        )
