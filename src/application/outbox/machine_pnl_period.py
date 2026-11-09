from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from beartype import beartype

from src.application.form_submissions import DeferredRetryOutboxError, NonRetryableOutboxError
from src.application.machine_pnl import ComputePeriodPnl, RentTermsPending
from src.application.machine_pnl.opex_params import OpExParamsPort
from src.application.machine_pnl.opex_ports import ServiceFactCounter, ZeroMaintenanceAlerter
from src.application.machine_pnl.ports import (
    MachineSalesWindowReader,
    PeriodPnlStore,
    PeriodSnapshotReader,
    UnitCostCatalog,
)
from src.application.machine_pnl.rent_ports import LocationRentOccupancyPort, RentAccountantAlerter
from src.application.machine_pnl.residual_ports import ResidualSessionReader
from src.application.outbox.handler_ids import MACHINE_PNL_PERIOD_HANDLER_ID
from src.domain.events import DomainEvent
from src.domain.ids import MachineId
from src.domain.machine_pnl.events import MachinePeriodPnlRequested


@beartype
@dataclass(frozen=True, slots=True)
class MachinePnlPeriodHandler:
    snapshots: PeriodSnapshotReader
    sales: MachineSalesWindowReader
    period_pnl_store: PeriodPnlStore
    load_unit_cost_catalog: Callable[[], UnitCostCatalog]
    residual_sessions: ResidualSessionReader
    load_opex_params: Callable[[], OpExParamsPort]
    service_facts: ServiceFactCounter
    zero_maintenance_alerter: ZeroMaintenanceAlerter
    load_location_rent: Callable[[], LocationRentOccupancyPort]
    rent_accountant_alerter: RentAccountantAlerter
    rent_pending_retry_hours: int
    rent_pending_max_attempts: int
    tax_enabled: bool = False

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, MachinePeriodPnlRequested):
            raise NonRetryableOutboxError(
                f"Unsupported machine pnl event: {type(event).__name__}",
            )
        catalog = await asyncio.to_thread(self.load_unit_cost_catalog)
        opex_params = await asyncio.to_thread(self.load_opex_params)
        location_rent = await asyncio.to_thread(self.load_location_rent)
        try:
            ComputePeriodPnl(
                snapshots=self.snapshots,
                sales=self.sales,
                unit_cost_catalog=catalog,
                period_pnl_store=self.period_pnl_store,
                residual_sessions=self.residual_sessions,
                opex_params=opex_params,
                service_facts=self.service_facts,
                zero_maintenance_alerter=self.zero_maintenance_alerter,
                location_rent=location_rent,
                tax_enabled=self.tax_enabled,
            ).execute(
                period_id=event.period_id,
                source_session_id=event.source_session_id,
            )
        except RentTermsPending as pending:
            snapshot = self.snapshots.get_by_period_id(event.period_id)
            if snapshot is not None:
                machine_id = snapshot.machine_id
                opened_at = snapshot.opened_at
                closed_at = snapshot.closed_at
            else:
                machine_id = MachineId(pending.machine_id or "unknown")
                opened_at = event.occurred_at
                closed_at = event.occurred_at
            self.rent_accountant_alerter.notify(
                period_id=event.period_id,
                machine_id=machine_id,
                opened_at=opened_at,
                closed_at=closed_at,
                next_retry_hours=self.rent_pending_retry_hours,
            )
            raise DeferredRetryOutboxError(
                str(pending),
                delay=timedelta(hours=self.rent_pending_retry_hours),
                max_attempts=self.rent_pending_max_attempts,
            ) from pending


__all__ = ["MACHINE_PNL_PERIOD_HANDLER_ID", "MachinePnlPeriodHandler"]
