from __future__ import annotations

import logging
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.allocate_residual import allocate_residual_for_period
from src.application.machine_pnl.cogs import (
    cogs_actual_for_line,
    cogs_expected_for_line,
    physical_qty,
)
from src.application.machine_pnl.errors import (
    AmbiguousResidualSessionError,
    IncompleteSnapshotError,
    MissingUnitCostError,
    RentTermsPending,
    SnackMachineError,
    SnapshotNotFoundError,
)
from src.application.machine_pnl.models import (
    FULL_SLICE_KEY,
    PeriodPnl,
    PnlWarning,
    make_pnl_id,
)
from src.application.machine_pnl.money import round_money
from src.application.machine_pnl.opex import compute_opex
from src.application.machine_pnl.opex_params import OpExParamsPort
from src.application.machine_pnl.opex_ports import ServiceFactCounter, ZeroMaintenanceAlerter
from src.application.machine_pnl.ports import (
    MachineSalesWindowReader,
    PeriodPnlStore,
    PeriodSnapshotReader,
    UnitCostCatalog,
)
from src.application.machine_pnl.rent_ports import LocationRentOccupancyPort
from src.application.machine_pnl.rent_slices import sum_rent_slices
from src.application.machine_pnl.residual_ports import ResidualSessionReader
from src.domain.machine_sales_classify import is_snack_machine_code

_LOGGER = logging.getLogger(__name__)
_ZERO = Decimal("0")


@beartype
class ComputePeriodPnl:
    def __init__(
        self,
        *,
        snapshots: PeriodSnapshotReader,
        sales: MachineSalesWindowReader,
        unit_cost_catalog: UnitCostCatalog,
        period_pnl_store: PeriodPnlStore,
        residual_sessions: ResidualSessionReader,
        opex_params: OpExParamsPort,
        service_facts: ServiceFactCounter,
        zero_maintenance_alerter: ZeroMaintenanceAlerter,
        location_rent: LocationRentOccupancyPort,
        tax_enabled: bool = False,
    ) -> None:
        self._snapshots = snapshots
        self._sales = sales
        self._unit_cost_catalog = unit_cost_catalog
        self._period_pnl_store = period_pnl_store
        self._residual_sessions = residual_sessions
        self._opex_params = opex_params
        self._service_facts = service_facts
        self._zero_maintenance_alerter = zero_maintenance_alerter
        self._location_rent = location_rent
        self._tax_enabled = tax_enabled

    def execute(self, *, period_id: str, source_session_id: str | None) -> PeriodPnl:
        snapshot = self._snapshots.get_by_period_id(period_id)
        if snapshot is None:
            raise SnapshotNotFoundError(period_id)
        if snapshot.status != "complete":
            raise IncompleteSnapshotError(period_id, status=snapshot.status)
        if is_snack_machine_code(snapshot.machine_id.value):
            raise SnackMachineError(period_id, machine_id=snapshot.machine_id.value)

        as_of = snapshot.closed_at.date()
        sales = self._sales.find_in_window(
            snapshot.machine_id,
            opened_at=snapshot.opened_at,
            closed_at=snapshot.closed_at,
        )

        revenue = Decimal("0")
        null_price_count = 0
        sale_count = 0
        for sale in sales:
            if sale.price is None:
                null_price_count += 1
                continue
            sale_count += 1
            revenue += sale.price * sale.quantity

        warnings: list[PnlWarning] = []
        if null_price_count > 0:
            warnings.append(
                PnlWarning(
                    code="null_price",
                    message=f"excluded {null_price_count} sale(s) with null price",
                    sku=None,
                )
            )

        cogs_expected = Decimal("0")
        cogs_actual = Decimal("0")
        for line in snapshot.lines:
            physical = physical_qty(
                actual_prev=line.actual_prev,
                loads_total=line.loads_total,
                actual=line.actual,
            )
            needs_cost = line.sales_total != 0 or physical != 0
            if needs_cost:
                unit_cost = self._unit_cost_catalog.get(line.product_code, as_of=as_of)
                if unit_cost is None:
                    raise MissingUnitCostError(
                        product_code=line.product_code,
                        as_of=as_of.isoformat(),
                        period_id=period_id,
                    )
                cogs_expected += cogs_expected_for_line(
                    sales_total=line.sales_total,
                    unit_cost=unit_cost,
                )
                cogs_actual += cogs_actual_for_line(physical=physical, unit_cost=unit_cost)
            if physical < 0:
                warnings.append(
                    PnlWarning(
                        code="negative_physical_qty",
                        message=f"negative physical qty for {line.product_code}: {physical}",
                        sku=line.product_code,
                    )
                )

        allocated_shortage = _ZERO
        allocated_surplus = _ZERO
        if snapshot.reconciled:
            matches = self._residual_sessions.find_completed_containing(
                period_id,
                technician_id=snapshot.responsible_technician_id,
            )
            if len(matches) > 1:
                _LOGGER.warning(
                    "machine_pnl residual ambiguous period_id=%s technician_id=%s count=%s",
                    period_id,
                    snapshot.responsible_technician_id.value,
                    len(matches),
                )
                raise AmbiguousResidualSessionError(
                    period_id=period_id,
                    technician_id=snapshot.responsible_technician_id.value,
                    count=len(matches),
                )
            if len(matches) == 1:
                found = matches[0]
                # source_session_id mismatch with found.session_id: ignore (no warning)
                alloc = allocate_residual_for_period(
                    period_id=period_id,
                    session=found,
                    snapshots=self._snapshots,
                    unit_cost_catalog=self._unit_cost_catalog,
                )
                allocated_shortage = alloc.allocated_shortage
                allocated_surplus = alloc.allocated_surplus
                warnings.extend(alloc.warnings)
                _LOGGER.info(
                    "machine_pnl residual allocated period_id=%s session_id=%s "
                    "shortage=%s surplus=%s",
                    period_id,
                    found.session_id,
                    allocated_shortage,
                    allocated_surplus,
                )

        params = self._opex_params.resolve(snapshot.machine_id, as_of=as_of)
        maintenance_count = self._service_facts.count_completed(
            snapshot.machine_id,
            opened_at=snapshot.opened_at,
            closed_at=snapshot.closed_at,
        )
        occupancies = self._location_rent.list_for_machine(snapshot.machine_id)
        try:
            rent = sum_rent_slices(
                occupancies=occupancies,
                opened_at=snapshot.opened_at,
                closed_at=snapshot.closed_at,
                revenue=revenue,
            )
        except RentTermsPending:
            _LOGGER.warning(
                "machine_pnl rent_terms_pending period_id=%s machine_id=%s",
                period_id,
                snapshot.machine_id.value,
            )
            raise RentTermsPending(
                period_id=period_id,
                machine_id=snapshot.machine_id.value,
            ) from None
        opex_result = compute_opex(
            params=params,
            revenue=revenue,
            sale_count=sale_count,
            maintenance_count=maintenance_count,
            opened_at=snapshot.opened_at,
            closed_at=snapshot.closed_at,
            rent_fixed=rent.rent_fixed,
            rent_percent=rent.rent_percent,
            tax_enabled=self._tax_enabled,
        )
        warnings.extend(opex_result.warnings)
        if any(w.code == "tax_pending_manual" for w in opex_result.warnings):
            _LOGGER.warning(
                "machine_pnl tax_pending_manual period_id=%s machine_id=%s tax=null",
                period_id,
                snapshot.machine_id.value,
            )
        if maintenance_count == 0:
            warnings.append(
                PnlWarning(
                    code="zero_maintenance_in_period",
                    message="no MaintenanceCompleted in period window",
                    sku=None,
                )
            )
            _LOGGER.warning(
                "machine_pnl zero_maintenance period_id=%s machine_id=%s "
                "maintenance_count=%s opex=%s",
                period_id,
                snapshot.machine_id.value,
                maintenance_count,
                opex_result.opex,
            )
            self._zero_maintenance_alerter.notify(
                period_id=period_id,
                machine_id=snapshot.machine_id,
                opened_at=snapshot.opened_at,
                closed_at=snapshot.closed_at,
                maintenance_count=maintenance_count,
            )

        revenue_r = round_money(revenue)
        cogs_expected_r = round_money(cogs_expected)
        cogs_actual_r = round_money(cogs_actual)
        allocated_shortage_r = round_money(allocated_shortage)
        allocated_surplus_r = round_money(allocated_surplus)
        opex = opex_result.opex
        net_before_residual = round_money(revenue_r - cogs_actual_r - opex)
        net_after_shortage = round_money(net_before_residual - allocated_shortage_r)

        _LOGGER.info(
            "machine_pnl period computed period_id=%s machine_id=%s maintenance_count=%s opex=%s",
            period_id,
            snapshot.machine_id.value,
            maintenance_count,
            opex,
        )

        covering = [
            occupancy
            for occupancy in occupancies
            if occupancy.installed_at <= snapshot.closed_at
            and (occupancy.removed_at is None or occupancy.removed_at > snapshot.closed_at)
        ]
        location_id = (
            max(covering, key=lambda occupancy: occupancy.installed_at).location_id
            if covering
            else None
        )
        technician_id = snapshot.responsible_technician_id.value

        slice_key = FULL_SLICE_KEY
        pnl = PeriodPnl(
            pnl_id=make_pnl_id(snapshot.period_id, slice_key=slice_key),
            period_id=snapshot.period_id,
            slice_key=slice_key,
            machine_id=snapshot.machine_id,
            opened_at=snapshot.opened_at,
            closed_at=snapshot.closed_at,
            revenue=revenue_r,
            cogs_expected=cogs_expected_r,
            cogs_actual=cogs_actual_r,
            allocated_shortage=allocated_shortage_r,
            allocated_surplus=allocated_surplus_r,
            opex=opex,
            opex_breakdown=opex_result.breakdown,
            net_before_residual=net_before_residual,
            net_after_shortage=net_after_shortage,
            warnings=tuple(warnings),
            location_id=location_id,
            technician_id=technician_id,
        )
        self._period_pnl_store.save(pnl, source_session_id=source_session_id)
        return pnl
