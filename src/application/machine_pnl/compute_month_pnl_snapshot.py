from __future__ import annotations

import calendar
import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.coffee_bom.expand_sales import expand_coffee_sales_via_domain
from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.machine_pnl.cogs import cogs_expected_for_line
from src.application.machine_pnl.company_as_of import resolve_month_company_id
from src.application.machine_pnl.errors import RentTermsPending
from src.application.machine_pnl.models import PeriodPnl, PnlWarning
from src.application.machine_pnl.money import round_money
from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.application.machine_pnl.month_ports import (
    MachineCompanyOccupancyReader,
    MonthPnlSnapshotStore,
)
from src.application.machine_pnl.month_projection import (
    LookbackPeriod,
    coverage_days,
    known_window_end,
    ratio_from_lookback,
    split_period_amount,
    waterfall,
)
from src.application.machine_pnl.opex import compute_opex, period_days
from src.application.machine_pnl.opex_params import OpExParamsPort
from src.application.machine_pnl.opex_ports import ServiceFactCounter
from src.application.machine_pnl.ports import (
    MachineSalesWindowReader,
    PeriodPnlStore,
    PeriodSnapshotReader,
    UnitCostCatalog,
)
from src.application.machine_pnl.rent_ports import LocationRentOccupancyPort
from src.application.machine_pnl.rent_slices import LocationRentOccupancy, sum_rent_slices
from src.application.product_identity.ports import DomainProductStore
from src.domain.coffee_bom.models import UnresolvedCoffeeRecipes
from src.domain.ids import MachineId
from src.domain.inventory_reconciliation.models import PeriodSaleLine
from src.domain.machine_sales import MachineSale

_LOGGER = logging.getLogger(__name__)
_ZERO = Decimal("0.00")
_BASIS_NONE = "none"
_BASIS_FACT = "fact"
_BASIS_DAY_COUNT = "day_count_fallback"
_BASIS_LAST_N = "last_n_periods_same_location"


def _last_day_of_month(period_start: date) -> date:
    last = calendar.monthrange(period_start.year, period_start.month)[1]
    return date(period_start.year, period_start.month, last)


def _inclusive_date_bounds(
    start: date,
    end: date,
    tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    opened_at = datetime.combine(start, time.min, tzinfo=tz) - timedelta(microseconds=1)
    closed_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz) - timedelta(
        microseconds=1,
    )
    return opened_at, closed_at


def _location_at(
    occupancies: tuple[LocationRentOccupancy, ...],
    at: datetime,
) -> str | None:
    covering = [
        occupancy
        for occupancy in occupancies
        if occupancy.installed_at <= at
        and (occupancy.removed_at is None or occupancy.removed_at > at)
    ]
    if not covering:
        return None
    return max(covering, key=lambda occupancy: occupancy.installed_at).location_id


def _day_covered(day: date, closed_ranges: tuple[tuple[date, date], ...]) -> bool:
    return any(opened <= day <= closed for opened, closed in closed_ranges)


def _tail_revenue(
    sales: tuple[MachineSale, ...],
    closed_ranges: tuple[tuple[date, date], ...],
) -> Decimal:
    total = _ZERO
    for sale in sales:
        if sale.sale_kind != "coffee" or sale.price is None:
            continue
        if _day_covered(sale.occurred_at.date(), closed_ranges):
            continue
        total += sale.price * sale.quantity
    return round_money(total)


@beartype
class ComputeMonthPnlSnapshot:
    def __init__(
        self,
        *,
        sales: MachineSalesWindowReader,
        unit_cost_catalog: UnitCostCatalog,
        recipes: CoffeeRecipeRepository,
        domain_products: DomainProductStore,
        period_pnl_store: PeriodPnlStore,
        snapshots: PeriodSnapshotReader,
        opex_params: OpExParamsPort,
        service_facts: ServiceFactCounter,
        location_rent: LocationRentOccupancyPort,
        company_occupancy: MachineCompanyOccupancyReader,
        month_store: MonthPnlSnapshotStore,
        ratio_lookback_periods: int,
        tz: ZoneInfo,
    ) -> None:
        self._sales = sales
        self._unit_cost_catalog = unit_cost_catalog
        self._recipes = recipes
        self._domain_products = domain_products
        self._period_pnl_store = period_pnl_store
        self._snapshots = snapshots
        self._opex_params = opex_params
        self._service_facts = service_facts
        self._location_rent = location_rent
        self._company_occupancy = company_occupancy
        self._month_store = month_store
        self._ratio_lookback_periods = ratio_lookback_periods
        self._tz = tz

    def execute(
        self,
        *,
        machine_id: MachineId,
        period_start: date,
        today: date,
    ) -> MonthPnlSnapshot:
        period_end = _last_day_of_month(period_start)
        known_end = known_window_end(
            period_start=period_start,
            period_end=period_end,
            today=today,
        )
        opened_at, closed_at = _inclusive_date_bounds(period_start, known_end, self._tz)
        warnings: list[PnlWarning] = []

        sales = self._sales.find_in_window(
            machine_id,
            opened_at=opened_at,
            closed_at=closed_at,
        )
        revenue, sale_count, cogs_expected, bom_warnings = self._stage1_cogs(
            sales,
            as_of=known_end,
        )
        warnings.extend(bom_warnings)

        occupancy_rows = self._company_occupancy.list_for_machine(machine_id)
        company_id, company_warnings = resolve_month_company_id(
            sales=sales,
            occupancies=occupancy_rows,
            period_start=period_start,
            period_end=period_end,
            tz=self._tz,
        )
        warnings.extend(company_warnings)

        occupancies = self._location_rent.list_for_machine(machine_id)
        try:
            rent = sum_rent_slices(
                occupancies=occupancies,
                opened_at=opened_at,
                closed_at=closed_at,
                revenue=revenue,
            )
            rent_fixed = rent.rent_fixed
            rent_percent = rent.rent_percent
        except RentTermsPending:
            rent_fixed = _ZERO
            rent_percent = _ZERO
            warnings.append(
                PnlWarning(
                    code="rent_terms_pending_soft",
                    message="rent terms unknown; persisting with rent 0",
                    sku=None,
                )
            )

        params = self._opex_params.resolve(machine_id, as_of=known_end)
        maintenance_count = self._service_facts.count_completed(
            machine_id,
            opened_at=opened_at,
            closed_at=closed_at,
        )
        opex_result = compute_opex(
            params=params,
            revenue=revenue,
            sale_count=sale_count,
            maintenance_count=maintenance_count,
            opened_at=opened_at,
            closed_at=closed_at,
            rent_fixed=rent_fixed,
            rent_percent=rent_percent,
            tax_enabled=False,
        )
        warnings.extend(opex_result.warnings)

        overlapping = self._period_pnl_store.list_overlapping(
            machine_id,
            range_start=datetime.combine(period_start, time.min, tzinfo=self._tz),
            range_end=datetime.combine(
                known_end + timedelta(days=1),
                time.min,
                tzinfo=self._tz,
            ),
        )
        (
            cogs_actual_fact,
            allocated_shortage_fact,
            allocated_surplus_fact,
            used_day_count_fallback,
        ) = self._split_overlapping_facts(
            overlapping,
            window_opened_at=opened_at,
            window_closed_at=closed_at,
            warnings=warnings,
        )
        closed_ranges = tuple((pnl.opened_at.date(), pnl.closed_at.date()) for pnl in overlapping)
        coverage = coverage_days(
            period_start=period_start,
            period_end=period_end,
            today=today,
            closed_ranges=closed_ranges,
        )
        location_id = _location_at(occupancies, closed_at)
        cogs_actual_estimate = _ZERO
        allocated_shortage_estimate = _ZERO
        allocated_surplus_estimate = _ZERO
        if coverage.elapsed_days > 0 and coverage.coverage_days == coverage.elapsed_days:
            projection_basis = _BASIS_DAY_COUNT if used_day_count_fallback else _BASIS_FACT
        else:
            tail_revenue = _tail_revenue(sales, closed_ranges)
            (
                cogs_actual_estimate,
                allocated_shortage_estimate,
                allocated_surplus_estimate,
                projection_basis,
            ) = self._tail_estimates(
                machine_id,
                occupancies=occupancies,
                location_id=location_id,
                tail_revenue=tail_revenue,
            )
            if projection_basis == _BASIS_NONE:
                warnings.append(
                    PnlWarning(
                        code="no_cost_history",
                        message="no closed periods on current location",
                        sku=None,
                    )
                )

        technician_id = None
        if overlapping:
            last = max(overlapping, key=lambda pnl: pnl.closed_at)
            technician_id = last.technician_id
            if technician_id is None:
                ir_snapshot = self._snapshots.get_by_period_id(last.period_id)
                if ir_snapshot is not None:
                    technician_id = ir_snapshot.responsible_technician_id.value

        cogs_actual_total = round_money(cogs_actual_fact + cogs_actual_estimate)
        tech_gap = round_money(allocated_shortage_fact + allocated_shortage_estimate)
        flow = waterfall(
            revenue=revenue,
            cogs_expected=cogs_expected,
            cogs_actual_total=cogs_actual_total,
            opex_known_total=opex_result.opex,
            tech_gap=tech_gap,
        )
        snapshot = MonthPnlSnapshot(
            machine_id=machine_id,
            location_id=location_id,
            technician_id=technician_id,
            period_start=period_start,
            period_end=period_end,
            revenue=revenue,
            revenue_known_as_of=known_end,
            cogs_expected=cogs_expected,
            cogs_actual_fact=cogs_actual_fact,
            cogs_actual_estimate=cogs_actual_estimate,
            allocated_shortage_fact=allocated_shortage_fact,
            allocated_shortage_estimate=allocated_shortage_estimate,
            allocated_surplus_fact=allocated_surplus_fact,
            allocated_surplus_estimate=allocated_surplus_estimate,
            opex_breakdown=opex_result.breakdown,
            opex_known_total=opex_result.opex,
            net_theory=flow.net_theory,
            machine_gap=flow.machine_gap,
            net_machine=flow.net_machine,
            tech_gap=flow.tech_gap,
            net_after_tech=flow.net_after_tech,
            coverage_days=coverage.coverage_days,
            days_in_month=coverage.days_in_month,
            coverage_pct=coverage.coverage_pct,
            projection_basis=projection_basis,
            warnings=tuple(warnings),
            last_recomputed_at=datetime.now(UTC),
            company_id=company_id,
        )
        _LOGGER.info(
            "machine_pnl month computed machine_id=%s month=%s coverage_pct=%s projection_basis=%s",
            machine_id.value,
            period_start.isoformat()[:7],
            snapshot.coverage_pct,
            snapshot.projection_basis,
        )
        self._month_store.upsert(snapshot)
        return snapshot

    def _split_overlapping_facts(
        self,
        overlapping: tuple[PeriodPnl, ...],
        *,
        window_opened_at: datetime,
        window_closed_at: datetime,
        warnings: list[PnlWarning],
    ) -> tuple[Decimal, Decimal, Decimal, bool]:
        cogs_actual_fact = _ZERO
        allocated_shortage_fact = _ZERO
        allocated_surplus_fact = _ZERO
        used_day_count_fallback = False
        for pnl in overlapping:
            frag_opened = max(pnl.opened_at, window_opened_at)
            frag_closed = min(pnl.closed_at, window_closed_at)
            if not (frag_opened < frag_closed):
                continue
            fragment_sales = self._sales.find_in_window(
                pnl.machine_id,
                opened_at=frag_opened,
                closed_at=frag_closed,
            )
            fragment_revenue = _ZERO
            for sale in fragment_sales:
                if sale.sale_kind == "coffee" and sale.price is not None:
                    fragment_revenue += sale.price * sale.quantity
            fragment_revenue = round_money(fragment_revenue)
            fragment_days = period_days(opened_at=frag_opened, closed_at=frag_closed)
            full_days = period_days(opened_at=pnl.opened_at, closed_at=pnl.closed_at)
            for amount, target in (
                (pnl.cogs_actual, "cogs"),
                (pnl.allocated_shortage, "shortage"),
                (pnl.allocated_surplus, "surplus"),
            ):
                split = split_period_amount(
                    amount=amount,
                    fragment_revenue=fragment_revenue,
                    period_revenue=pnl.revenue,
                    fragment_days=fragment_days,
                    period_days=full_days,
                )
                if split.used_day_count_fallback:
                    used_day_count_fallback = True
                if target == "cogs":
                    cogs_actual_fact += split.value
                elif target == "shortage":
                    allocated_shortage_fact += split.value
                else:
                    allocated_surplus_fact += split.value
        if used_day_count_fallback:
            warnings.append(
                PnlWarning(
                    code="zero_revenue_period_split_fallback",
                    message="period revenue is 0; split by day count",
                    sku=None,
                )
            )
        return (
            round_money(cogs_actual_fact),
            round_money(allocated_shortage_fact),
            round_money(allocated_surplus_fact),
            used_day_count_fallback,
        )

    def _tail_estimates(
        self,
        machine_id: MachineId,
        *,
        occupancies: tuple[LocationRentOccupancy, ...],
        location_id: str | None,
        tail_revenue: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal, str]:
        history = sorted(
            self._period_pnl_store.list_for_machine(machine_id),
            key=lambda pnl: pnl.closed_at,
            reverse=True,
        )
        lookback_cogs: list[LookbackPeriod] = []
        lookback_shortage: list[LookbackPeriod] = []
        lookback_surplus: list[LookbackPeriod] = []
        for pnl in history:
            loc = pnl.location_id or _location_at(occupancies, pnl.closed_at)
            days = period_days(opened_at=pnl.opened_at, closed_at=pnl.closed_at)
            lookback_cogs.append(
                LookbackPeriod(
                    location_id=loc,
                    days=days,
                    revenue=pnl.revenue,
                    amount=pnl.cogs_actual,
                )
            )
            lookback_shortage.append(
                LookbackPeriod(
                    location_id=loc,
                    days=days,
                    revenue=pnl.revenue,
                    amount=pnl.allocated_shortage,
                )
            )
            lookback_surplus.append(
                LookbackPeriod(
                    location_id=loc,
                    days=days,
                    revenue=pnl.revenue,
                    amount=pnl.allocated_surplus,
                )
            )
        last_n = self._ratio_lookback_periods
        cogs_ratio = ratio_from_lookback(lookback_cogs, location_id=location_id, last_n=last_n)
        shortage_ratio = ratio_from_lookback(
            lookback_shortage,
            location_id=location_id,
            last_n=last_n,
        )
        surplus_ratio = ratio_from_lookback(
            lookback_surplus,
            location_id=location_id,
            last_n=last_n,
        )
        if (
            cogs_ratio.ratio is None
            and shortage_ratio.ratio is None
            and surplus_ratio.ratio is None
        ):
            return _ZERO, _ZERO, _ZERO, _BASIS_NONE

        def _apply(ratio: Decimal | None) -> Decimal:
            if ratio is None:
                return _ZERO
            return round_money(ratio * tail_revenue)

        return (
            _apply(cogs_ratio.ratio),
            _apply(shortage_ratio.ratio),
            _apply(surplus_ratio.ratio),
            _BASIS_LAST_N,
        )

    def _stage1_cogs(
        self,
        sales: tuple[MachineSale, ...],
        *,
        as_of: date,
    ) -> tuple[Decimal, int, Decimal, list[PnlWarning]]:
        warnings: list[PnlWarning] = []
        coffee_priced = [
            sale for sale in sales if sale.sale_kind == "coffee" and sale.price is not None
        ]
        revenue = _ZERO
        for sale in coffee_priced:
            assert sale.price is not None
            revenue += sale.price * sale.quantity
        revenue = round_money(revenue)
        sale_count = len(coffee_priced)
        if not coffee_priced:
            return revenue, sale_count, _ZERO, warnings

        period_sales = tuple(
            PeriodSaleLine(
                product_code=sale.product_code,
                quantity=sale.quantity,
                occurred_at=sale.occurred_at,
            )
            for sale in coffee_priced
        )
        expanded = expand_coffee_sales_via_domain(
            period_sales,
            recipe_repo=self._recipes,
            products=self._domain_products,
        )
        if isinstance(expanded, UnresolvedCoffeeRecipes):
            for code in expanded.bundle_codes:
                warnings.append(
                    PnlWarning(
                        code="unresolved_bom",
                        message=f"unresolved coffee recipe for bundle {code}",
                        sku=code,
                    )
                )
            return revenue, sale_count, _ZERO, warnings

        cogs_expected = _ZERO
        missing_cost_skus: set[str] = set()
        for line in expanded:
            unit_cost = self._unit_cost_catalog.get(line.product_code, as_of=as_of)
            if unit_cost is None:
                if line.product_code not in missing_cost_skus:
                    missing_cost_skus.add(line.product_code)
                    warnings.append(
                        PnlWarning(
                            code="missing_unit_cost_soft",
                            message=f"missing unit cost for {line.product_code}",
                            sku=line.product_code,
                        )
                    )
                continue
            cogs_expected += cogs_expected_for_line(
                sales_total=line.quantity,
                unit_cost=unit_cost,
            )
        return revenue, sale_count, round_money(cogs_expected), warnings
