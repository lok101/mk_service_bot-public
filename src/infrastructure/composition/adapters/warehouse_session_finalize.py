from __future__ import annotations

from datetime import UTC, datetime

from beartype import beartype

from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.domain.ids import TechnicianId


@beartype
class WarehouseSessionFinalizeAdapter:
    executor: TechnicianWarehouseExecutor

    def __init__(self, *, executor: TechnicianWarehouseExecutor) -> None:
        self.executor = executor

    @beartype
    def finalize_transfers(self, session_id: str) -> None:
        technician_id = TechnicianId(session_id.split(":", maxsplit=1)[0])
        repository = self.executor.repository
        if repository.has_finalized_transfers_for_session(
            technician_id,
            session_id=session_id,
        ):
            return

        warehouse = repository.get(technician_id)
        domain_delta = warehouse.latest_warehouse_delta()
        if domain_delta is None:
            # Inventory path (model B): delta is compute-on-demand, not frozen on count.
            # Accepted risk: Finalized ids from current stream, not draft.transfer_refs —
            # docs/operational-assumptions.md § Finalize:
            # TransferFinalized ids vs ReconciliationDraft
            domain_delta = warehouse.compute_warehouse_delta_between_latest_inventories()
        if domain_delta is None:
            return

        self.executor.execute(
            technician_id,
            lambda aggregate: aggregate.finalize_transfers(
                session_id=session_id,
                external_document_ids=domain_delta.transfer_document_ids,
                finalized_at=datetime.now(tz=UTC),
            ),
        )
