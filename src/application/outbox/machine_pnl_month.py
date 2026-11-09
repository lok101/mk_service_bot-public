from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.machine_pnl import ComputeMonthPnlSnapshot
from src.application.machine_pnl.month_ports import (
    MachineCompanyOccupancyReader,
    MonthPnlSnapshotStore,
)
from src.application.machine_pnl.opex_params import OpExParamsPort
from src.application.machine_pnl.opex_ports import ServiceFactCounter
from src.application.machine_pnl.ports import (
    MachineSalesWindowReader,
    PeriodPnlStore,
    PeriodSnapshotReader,
    UnitCostCatalog,
)
from src.application.machine_pnl.rent_ports import LocationRentOccupancyPort
from src.application.outbox.handler_ids import MACHINE_PNL_MONTH_HANDLER_ID
from src.domain.events import DomainEvent
from src.domain.ids import MachineId
from src.domain.machine_pnl.events import MachineMonthPnlRequested


@beartype
@dataclass(frozen=True, slots=True)
class MachinePnlMonthHandler:
    snapshots: PeriodSnapshotReader
    sales: MachineSalesWindowReader
    period_pnl_store: PeriodPnlStore
    month_store: MonthPnlSnapshotStore
    recipes: object
    domain_products: object
    load_unit_cost_catalog: Callable[[], UnitCostCatalog]
    load_opex_params: Callable[[], OpExParamsPort]
    service_facts: ServiceFactCounter
    load_location_rent: Callable[[], LocationRentOccupancyPort]
    company_occupancy: MachineCompanyOccupancyReader
    ratio_lookback_periods: int
    tz: ZoneInfo

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, MachineMonthPnlRequested):
            raise NonRetryableOutboxError(
                f"Unsupported machine pnl month event: {type(event).__name__}",
            )
        catalog = await asyncio.to_thread(self.load_unit_cost_catalog)
        opex_params = await asyncio.to_thread(self.load_opex_params)
        location_rent = await asyncio.to_thread(self.load_location_rent)
        use_case = ComputeMonthPnlSnapshot(
            sales=self.sales,
            unit_cost_catalog=catalog,
            recipes=self.recipes,  # type: ignore[arg-type]
            domain_products=self.domain_products,  # type: ignore[arg-type]
            period_pnl_store=self.period_pnl_store,
            snapshots=self.snapshots,
            opex_params=opex_params,
            service_facts=self.service_facts,
            location_rent=location_rent,
            company_occupancy=self.company_occupancy,
            month_store=self.month_store,
            ratio_lookback_periods=self.ratio_lookback_periods,
            tz=self.tz,
        )
        today = date.today()
        machine_id = MachineId(event.machine_id)
        for period_start in event.period_start_dates:
            use_case.execute(
                machine_id=machine_id,
                period_start=period_start,
                today=today,
            )


__all__ = ["MACHINE_PNL_MONTH_HANDLER_ID", "MachinePnlMonthHandler"]
