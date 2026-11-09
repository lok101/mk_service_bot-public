from __future__ import annotations

from beartype import beartype

from src.application.machine_pnl.residual_ports import ResidualSessionView
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.domain.ids import TechnicianId
from src.domain.technician_settlement.events import (
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)


@beartype
class SettlementResidualSessionReader:
    def __init__(self, settlement_repository: TechnicianSettlementRepository) -> None:
        self._settlement_repository = settlement_repository

    def find_completed_containing(
        self,
        period_id: str,
        *,
        technician_id: TechnicianId,
    ) -> tuple[ResidualSessionView, ...]:
        events = self._settlement_repository.event_store.get_events_for_technician(
            technician_id,
        )
        views: list[ResidualSessionView] = []
        for event in events:
            if not isinstance(
                event,
                (
                    TechnicianReconciliationSessionCompleted,
                    TechnicianReconciliationSessionCommitted,
                ),
            ):
                continue
            if period_id not in event.period_ids:
                continue
            views.append(
                ResidualSessionView(
                    session_id=event.session_id.value,
                    technician_id=event.technician_id.value,
                    anchor_at=event.anchor_at,
                    period_ids=event.period_ids,
                    residual_by_sku=dict(event.residual_by_sku),
                )
            )
        return tuple(views)
