from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from tests.application.machine_pnl.fakes import (
    InMemoryLocationRentOccupancyPort,
    InMemoryMachineSalesWindowReader,
    InMemoryOpExParamsPort,
    InMemoryPeriodPnlStore,
    InMemoryPeriodSnapshotReader,
    InMemoryServiceFactCounter,
    InMemoryUnitCostCatalog,
)
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.inventory_reconciliation import MachineCompanyOccupancy
from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.application.machine_pnl.opex_breakdown import empty_opex_breakdown
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.product_identity.models import DomainProduct
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale
from src.infrastructure.machine_pnl.month_memory import InMemoryMonthPnlSnapshotStore
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)

_MACHINE = MachineId("101")
_TZ = ZoneInfo("UTC")
_LATTE = CoffeeRecipe(
    drink_product_id="drink-latte",
    name="Latte",
    components=(
        CoffeeRecipeComponent(
            ingredient_product_id="ing-coffee",
            quantity_per_unit=Decimal("12.5"),
        ),
        CoffeeRecipeComponent(
            ingredient_product_id="ing-cup",
            quantity_per_unit=Decimal("1"),
        ),
    ),
)


def _minimal_month(
    *,
    revenue: Decimal = Decimal("0.00"),
    machine_id: MachineId = _MACHINE,
) -> MonthPnlSnapshot:
    return MonthPnlSnapshot(
        machine_id=machine_id,
        location_id=None,
        technician_id=None,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        revenue=revenue,
        revenue_known_as_of=date(2026, 6, 30),
        cogs_expected=Decimal("0.00"),
        cogs_actual_fact=Decimal("0.00"),
        cogs_actual_estimate=Decimal("0.00"),
        allocated_shortage_fact=Decimal("0.00"),
        allocated_shortage_estimate=Decimal("0.00"),
        allocated_surplus_fact=Decimal("0.00"),
        allocated_surplus_estimate=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        opex_known_total=Decimal("0.00"),
        net_theory=Decimal("0.00"),
        machine_gap=Decimal("0.00"),
        net_machine=Decimal("0.00"),
        tech_gap=Decimal("0.00"),
        net_after_tech=Decimal("0.00"),
        coverage_days=0,
        days_in_month=30,
        coverage_pct=Decimal("0"),
        projection_basis="none",
        warnings=(),
        last_recomputed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def _minimal_pnl_for_month(
    *,
    period_id: str = "p-1",
    opened_at: datetime,
    closed_at: datetime,
    revenue: Decimal = Decimal("0.00"),
    cogs_actual: Decimal = Decimal("0.00"),
    allocated_shortage: Decimal = Decimal("0.00"),
    allocated_surplus: Decimal = Decimal("0.00"),
    location_id: str | None = "loc-a",
    technician_id: str | None = "tech-1",
):
    from src.application.machine_pnl.models import FULL_SLICE_KEY, PeriodPnl, make_pnl_id

    return PeriodPnl(
        pnl_id=make_pnl_id(period_id),
        period_id=period_id,
        slice_key=FULL_SLICE_KEY,
        machine_id=_MACHINE,
        opened_at=opened_at,
        closed_at=closed_at,
        revenue=revenue,
        cogs_expected=Decimal("0.00"),
        cogs_actual=cogs_actual,
        allocated_shortage=allocated_shortage,
        allocated_surplus=allocated_surplus,
        opex=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        net_before_residual=Decimal("0.00"),
        net_after_shortage=Decimal("0.00"),
        warnings=(),
        location_id=location_id,
        technician_id=technician_id,
    )


def _sale(
    *,
    occurred_at: datetime,
    qty: Decimal = Decimal("2"),
    price: Decimal = Decimal("50"),
    code: str = "2301",
    source_id: str = "s1",
    company_id: int | None = None,
) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=_MACHINE,
        product_code=code,
        quantity=qty,
        occurred_at=occurred_at,
        ingested_at=occurred_at,
        sale_kind="coffee",
        price=price,
        company_id=company_id,
    )


def _month_use_case(
    *,
    sales: tuple[MachineSale, ...] = (),
    period_pnls: tuple = (),
    recipes: dict | None = None,
    costs: dict[str, Decimal] | None = None,
    occupancy: LocationRentOccupancy | None = None,
    company_occupancies: tuple[MachineCompanyOccupancy, ...] = (),
):
    sales_reader = InMemoryMachineSalesWindowReader()
    for sale in sales:
        sales_reader.add(sale)
    catalog = InMemoryUnitCostCatalog()
    for sku, cost in (costs or {"coffee-1": Decimal("2"), "cup-1": Decimal("1")}).items():
        catalog.set(sku, as_of=date(2026, 6, 30), cost=cost)
        catalog.set(sku, as_of=date(2026, 7, 1), cost=cost)
    recipes_repo = InMemoryCoffeeRecipeRepository()
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="drink-latte",
            number="D-LATTE",
            name="Latte",
            catalog_code=None,
            hidden=False,
            kind="coffee_drink",
            legacy_ms_code="2301",
        ),
    )
    products.insert(
        DomainProduct(
            domain_product_id="ing-coffee",
            number="I-COFFEE",
            name="Coffee",
            catalog_code="coffee-1",
            hidden=False,
            kind="coffee_ingredient",
        ),
    )
    products.insert(
        DomainProduct(
            domain_product_id="ing-cup",
            number="I-CUP",
            name="Cup",
            catalog_code="cup-1",
            hidden=False,
            kind="coffee_ingredient",
        ),
    )
    for recipe in (recipes or {"2301": _LATTE}).values():
        recipes_repo.upsert(recipe)
    period_store = InMemoryPeriodPnlStore()
    for pnl in period_pnls:
        period_store.save(pnl, source_session_id=None)
    rent = InMemoryLocationRentOccupancyPort()
    occ = occupancy or LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE,
        installed_at=datetime(2026, 1, 1, tzinfo=UTC),
        removed_at=None,
        rent_monthly=Decimal("0"),
        rent_percent=None,
    )
    rent.set(_MACHINE, (occ,))
    month_store = InMemoryMonthPnlSnapshotStore()
    from src.application.machine_pnl.compute_month_pnl_snapshot import ComputeMonthPnlSnapshot

    company_store = InMemoryMachineCompanyOccupancyStore()
    if company_occupancies:
        company_store.replace_for_machine(_MACHINE, company_occupancies)

    use_case = ComputeMonthPnlSnapshot(
        sales=sales_reader,
        unit_cost_catalog=catalog,
        recipes=recipes_repo,
        domain_products=products,
        period_pnl_store=period_store,
        snapshots=InMemoryPeriodSnapshotReader(),
        opex_params=InMemoryOpExParamsPort.zeros(),
        service_facts=InMemoryServiceFactCounter(),
        location_rent=rent,
        company_occupancy=company_store,
        month_store=month_store,
        ratio_lookback_periods=3,
        tz=_TZ,
    )
    return use_case, month_store


def test_in_memory_month_store_upsert_idempotent() -> None:
    store = InMemoryMonthPnlSnapshotStore()
    first = _minimal_month(revenue=Decimal("10.00"))
    second = _minimal_month(revenue=Decimal("20.00"))
    store.upsert(first)
    store.upsert(second)
    loaded = store.get(first.machine_id, first.period_start)
    assert loaded is not None
    assert loaded.revenue == Decimal("20.00")


def test_cogs_expected_from_window_sales_without_closed_period() -> None:
    sale = _sale(occurred_at=datetime(2026, 6, 10, tzinfo=UTC))
    use_case, month_store = _month_use_case(sales=(sale,))
    snapshot = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snapshot.cogs_expected == Decimal("52.00")
    assert snapshot.revenue == Decimal("100.00")
    assert snapshot.cogs_actual_fact == Decimal("0.00")
    assert snapshot.projection_basis == "none"
    assert any(w.code == "no_cost_history" for w in snapshot.warnings)
    loaded = month_store.get(_MACHINE, date(2026, 6, 1))
    assert loaded == snapshot


def test_unresolved_bom_soft_zero() -> None:
    sale = _sale(occurred_at=datetime(2026, 6, 10, tzinfo=UTC), code="9999")
    use_case, month_store = _month_use_case(sales=(sale,), recipes={})
    snapshot = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snapshot.cogs_expected == Decimal("0.00")
    assert any(w.code == "unresolved_bom" and w.sku == "9999" for w in snapshot.warnings)
    assert month_store.get(_MACHINE, date(2026, 6, 1)) is not None


def test_missing_unit_cost_soft_zero() -> None:
    sale = _sale(occurred_at=datetime(2026, 6, 10, tzinfo=UTC))
    use_case, month_store = _month_use_case(
        sales=(sale,),
        costs={"coffee-1": Decimal("2")},  # cup-1 missing
    )
    snapshot = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snapshot.cogs_expected == Decimal("50.00")  # 2 * 12.5 * 2; cup skipped
    assert any(w.code == "missing_unit_cost_soft" and w.sku == "cup-1" for w in snapshot.warnings)
    assert month_store.get(_MACHINE, date(2026, 6, 1)) is not None


def test_fully_closed_month_is_fact() -> None:
    sale = _sale(occurred_at=datetime(2026, 6, 10, tzinfo=UTC))
    period = _minimal_pnl_for_month(
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 30, 23, 59, tzinfo=UTC),
        revenue=Decimal("100.00"),
        cogs_actual=Decimal("80.00"),
        allocated_shortage=Decimal("5.00"),
        allocated_surplus=Decimal("2.00"),
        location_id="loc-a",
        technician_id="tech-1",
    )
    use_case, _store = _month_use_case(sales=(sale,), period_pnls=(period,))
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 7, 1),
    )
    assert snap.projection_basis == "fact"
    assert snap.coverage_pct == Decimal("100")
    assert snap.cogs_actual_fact == Decimal("80.00")
    assert snap.cogs_actual_estimate == Decimal("0.00")
    assert snap.allocated_shortage_fact == Decimal("5.00")
    assert snap.allocated_surplus_fact == Decimal("2.00")
    assert snap.allocated_surplus_estimate == Decimal("0.00")
    assert snap.net_theory - snap.machine_gap == snap.net_machine
    assert snap.net_machine - snap.tech_gap == snap.net_after_tech
    assert snap.tech_gap == Decimal("5.00")


def test_open_tail_mixes_fact_and_estimate() -> None:
    closed_sale = _sale(
        occurred_at=datetime(2026, 6, 10, tzinfo=UTC),
        qty=Decimal("2"),
        price=Decimal("40"),
    )
    tail_sale = MachineSale(
        source_id="s2",
        machine_id=_MACHINE,
        product_code="2301",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 6, 25, tzinfo=UTC),
        ingested_at=datetime(2026, 6, 25, tzinfo=UTC),
        sale_kind="coffee",
        price=Decimal("20"),
    )
    period = _minimal_pnl_for_month(
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 20, tzinfo=UTC),
        revenue=Decimal("80.00"),
        cogs_actual=Decimal("40.00"),
        location_id="loc-a",
        technician_id="tech-1",
    )
    use_case, _store = _month_use_case(
        sales=(closed_sale, tail_sale),
        period_pnls=(period,),
    )
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snap.cogs_actual_fact > 0
    assert snap.cogs_actual_estimate > 0
    assert snap.coverage_pct < Decimal("100")
    assert snap.projection_basis == "last_n_periods_same_location"


def test_new_machine_projection_basis_none() -> None:
    old = _minimal_pnl_for_month(
        opened_at=datetime(2026, 4, 1, tzinfo=UTC),
        closed_at=datetime(2026, 4, 20, tzinfo=UTC),
        revenue=Decimal("100.00"),
        cogs_actual=Decimal("90.00"),
        location_id="loc-old",
        technician_id="tech-1",
    )
    occ = LocationRentOccupancy(
        location_id="loc-new",
        machine_id=_MACHINE,
        installed_at=datetime(2026, 6, 1, tzinfo=UTC),
        removed_at=None,
        rent_monthly=Decimal("0"),
        rent_percent=None,
    )
    sale = _sale(occurred_at=datetime(2026, 6, 10, tzinfo=UTC))
    use_case, _store = _month_use_case(sales=(sale,), period_pnls=(old,), occupancy=occ)
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snap.projection_basis == "none"
    assert snap.cogs_actual_estimate == Decimal("0.00")
    assert any(w.code == "no_cost_history" for w in snap.warnings)
    assert snap.cogs_expected > 0


def test_relocation_excludes_old_location_from_ratio() -> None:
    old = _minimal_pnl_for_month(
        opened_at=datetime(2026, 4, 1, tzinfo=UTC),
        closed_at=datetime(2026, 4, 20, tzinfo=UTC),
        revenue=Decimal("100.00"),
        cogs_actual=Decimal("90.00"),
        location_id="loc-old",
        technician_id="tech-old",
    )
    occ = LocationRentOccupancy(
        location_id="loc-new",
        machine_id=_MACHINE,
        installed_at=datetime(2026, 6, 1, tzinfo=UTC),
        removed_at=None,
        rent_monthly=Decimal("0"),
        rent_percent=None,
    )
    sale = _sale(occurred_at=datetime(2026, 6, 10, tzinfo=UTC))
    use_case, _store = _month_use_case(sales=(sale,), period_pnls=(old,), occupancy=occ)
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snap.projection_basis == "none"
    assert snap.location_id == "loc-new"


def test_zero_revenue_period_split_warning() -> None:
    period = _minimal_pnl_for_month(
        opened_at=datetime(2026, 5, 20, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
        revenue=Decimal("0.00"),
        cogs_actual=Decimal("30.00"),
        location_id="loc-a",
        technician_id="tech-1",
    )
    use_case, _store = _month_use_case(period_pnls=(period,))
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert any(w.code == "zero_revenue_period_split_fallback" for w in snap.warnings)


def test_rent_terms_pending_soft_persists() -> None:
    occ = LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE,
        installed_at=datetime(2026, 1, 1, tzinfo=UTC),
        removed_at=None,
        rent_monthly=None,
        rent_percent=None,
    )
    sale = _sale(occurred_at=datetime(2026, 6, 10, tzinfo=UTC))
    use_case, month_store = _month_use_case(sales=(sale,), occupancy=occ)
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert any(w.code == "rent_terms_pending_soft" for w in snap.warnings)
    assert month_store.get(_MACHINE, date(2026, 6, 1)) is not None


def test_technician_id_is_last_closed_period() -> None:
    a = _minimal_pnl_for_month(
        period_id="p-a",
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
        technician_id="tech-a",
        location_id="loc-a",
        revenue=Decimal("40.00"),
        cogs_actual=Decimal("10.00"),
    )
    b = _minimal_pnl_for_month(
        period_id="p-b",
        opened_at=datetime(2026, 6, 11, tzinfo=UTC),
        closed_at=datetime(2026, 6, 25, tzinfo=UTC),
        technician_id="tech-b",
        location_id="loc-a",
        revenue=Decimal("40.00"),
        cogs_actual=Decimal("10.00"),
    )
    use_case, _store = _month_use_case(period_pnls=(a, b))
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snap.technician_id == "tech-b"


def test_two_technicians_one_row() -> None:
    a = _minimal_pnl_for_month(
        period_id="p-a",
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
        technician_id="tech-a",
        location_id="loc-a",
    )
    b = _minimal_pnl_for_month(
        period_id="p-b",
        opened_at=datetime(2026, 6, 11, tzinfo=UTC),
        closed_at=datetime(2026, 6, 25, tzinfo=UTC),
        technician_id="tech-b",
        location_id="loc-a",
    )
    use_case, month_store = _month_use_case(period_pnls=(a, b))
    use_case.execute(machine_id=_MACHINE, period_start=date(2026, 6, 1), today=date(2026, 6, 30))
    use_case.execute(machine_id=_MACHINE, period_start=date(2026, 6, 1), today=date(2026, 6, 30))
    assert month_store.get(_MACHINE, date(2026, 6, 1)) is not None
    assert len(month_store._by_key) == 1


def test_location_id_none_period_fallback_occupancy() -> None:
    period = _minimal_pnl_for_month(
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 20, tzinfo=UTC),
        location_id=None,
        technician_id="tech-1",
        revenue=Decimal("80.00"),
        cogs_actual=Decimal("40.00"),
    )
    use_case, _store = _month_use_case(period_pnls=(period,))
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snap.location_id == "loc-a"


def test_technician_id_none_period_fallback_snapshot() -> None:
    period = _minimal_pnl_for_month(
        period_id="p-ir",
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 20, tzinfo=UTC),
        location_id="loc-a",
        technician_id=None,
        revenue=Decimal("80.00"),
        cogs_actual=Decimal("40.00"),
    )
    use_case, _store = _month_use_case(period_pnls=(period,))
    use_case._snapshots.save(
        ResponsibilityPeriodReconciliation(
            period_id="p-ir",
            machine_id=_MACHINE,
            responsible_technician_id=TechnicianId("tech-from-ir"),
            opening_revision_id=RevisionId("o"),
            closing_revision_id=RevisionId("c"),
            opened_at=datetime(2026, 6, 1, tzinfo=UTC),
            closed_at=datetime(2026, 6, 20, tzinfo=UTC),
            lines=(),
            sales_lines=(),
            load_count=0,
            status="complete",  # type: ignore[arg-type]
            reconciled=True,
        )
    )
    snap = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snap.technician_id == "tech-from-ir"


def test_stage1_failure_does_not_clobber_existing_snapshot() -> None:
    use_case, month_store = _month_use_case()
    month_store.upsert(_minimal_month(revenue=Decimal("99.00")))

    class _BoomSales:
        def find_in_window(self, machine_id, *, opened_at, closed_at):
            raise RuntimeError("sheets down")

    use_case._sales = _BoomSales()
    with pytest.raises(RuntimeError, match="sheets down"):
        use_case.execute(
            machine_id=_MACHINE,
            period_start=date(2026, 6, 1),
            today=date(2026, 6, 30),
        )
    loaded = month_store.get(_MACHINE, date(2026, 6, 1))
    assert loaded is not None
    assert loaded.revenue == Decimal("99.00")


def test_compute_persists_company_id_from_month_sales() -> None:
    sale = _sale(
        occurred_at=datetime(2026, 6, 10, tzinfo=UTC),
        company_id=42,
    )
    use_case, month_store = _month_use_case(sales=(sale,))
    snapshot = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snapshot.company_id == 42
    loaded = month_store.get(_MACHINE, date(2026, 6, 1))
    assert loaded is not None
    assert loaded.company_id == 42


def test_compute_majority_keeps_single_month_row() -> None:
    sales = (
        _sale(
            occurred_at=datetime(2026, 6, 2, tzinfo=UTC),
            qty=Decimal("1"),
            price=Decimal("10"),
            source_id="s-a",
            company_id=1,
        ),
        _sale(
            occurred_at=datetime(2026, 6, 20, tzinfo=UTC),
            qty=Decimal("3"),
            price=Decimal("10"),
            source_id="s-b",
            company_id=2,
        ),
    )
    use_case, month_store = _month_use_case(sales=sales)
    snapshot = use_case.execute(
        machine_id=_MACHINE,
        period_start=date(2026, 6, 1),
        today=date(2026, 6, 30),
    )
    assert snapshot.company_id == 2
    assert any(item.code == "company_majority_assumption" for item in snapshot.warnings)
    loaded = month_store.get(_MACHINE, date(2026, 6, 1))
    assert loaded is not None
    assert loaded.company_id == 2
    assert loaded.machine_id == _MACHINE
    assert loaded.period_start == date(2026, 6, 1)
