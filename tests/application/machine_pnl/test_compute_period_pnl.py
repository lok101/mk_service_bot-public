from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.application.machine_pnl.fakes import (
    InMemoryLocationRentOccupancyPort,
    InMemoryMachineSalesWindowReader,
    InMemoryOpExParamsPort,
    InMemoryPeriodPnlStore,
    InMemoryPeriodSnapshotReader,
    InMemoryResidualSessionReader,
    InMemoryServiceFactCounter,
    InMemoryUnitCostCatalog,
    NoOpZeroMaintenanceAlerter,
    RecordingZeroMaintenanceAlerter,
)

from src.application.machine_pnl import ComputePeriodPnl
from src.application.machine_pnl.errors import (
    AmbiguousResidualSessionError,
    IncompleteSnapshotError,
    MissingUnitCostError,
    SnapshotNotFoundError,
)
from src.application.machine_pnl.models import PeriodPnl, PnlWarning, make_pnl_id
from src.application.machine_pnl.money import round_money
from src.application.machine_pnl.opex_breakdown import OPEX_BREAKDOWN_KEYS, empty_opex_breakdown
from src.application.machine_pnl.opex_params import (
    FixtureMachineOpExRow,
    FixtureOpExParamsCatalog,
    FixtureRateRow,
    OpExParamsPort,
)
from src.application.machine_pnl.opex_ports import ServiceFactCounter, ZeroMaintenanceAlerter
from src.application.machine_pnl.rent_ports import LocationRentOccupancyPort
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.machine_pnl.residual_ports import ResidualSessionView
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale

_MACHINE_ID = MachineId("101")
_TECHNICIAN_ID = TechnicianId("tech-1")
_OPENED_AT = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED_AT = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_ANCHOR_AT = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
_PERIOD_ID = "period-101"
_PERIOD_SIBLING = "period-102"
_SESSION_ID = "session-abc"
_SKU = "coffee-beans"


def _zero_rent_occupancy(
    *,
    machine_id: MachineId = _MACHINE_ID,
    opened_at: datetime = _OPENED_AT,
) -> LocationRentOccupancy:
    return LocationRentOccupancy(
        location_id="loc-test",
        machine_id=machine_id,
        installed_at=opened_at,
        removed_at=None,
        rent_monthly=Decimal("0"),
        rent_percent=None,
    )


def _snapshot(
    *,
    period_id: str = _PERIOD_ID,
    machine_id: MachineId = _MACHINE_ID,
    status: str = "complete",
    reconciled: bool = True,
    lines: tuple[ReconciliationLine, ...] | None = None,
    sales_total: Decimal | None = None,
) -> ResponsibilityPeriodReconciliation:
    if lines is None:
        line_sales = Decimal("3") if sales_total is None else sales_total
        lines = (
            ReconciliationLine(
                product_code=_SKU,
                actual_prev=Decimal("10"),
                actual=Decimal("7"),
                calculated=Decimal("5"),
                delta=Decimal("2"),
                loads_total=Decimal("0"),
                sales_total=line_sales,
            ),
        )
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=machine_id,
        responsible_technician_id=_TECHNICIAN_ID,
        opening_revision_id=RevisionId("rev-open"),
        closing_revision_id=RevisionId("rev-close"),
        opened_at=_OPENED_AT,
        closed_at=_CLOSED_AT,
        lines=lines,
        sales_lines=(),
        load_count=0,
        status=status,  # type: ignore[arg-type]
        reconciled=reconciled,
    )


def _sale(
    *,
    source_id: str,
    price: Decimal | None,
    quantity: Decimal = Decimal("1"),
    product_code: str = _SKU,
    occurred_at: datetime | None = None,
) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=_MACHINE_ID,
        product_code=product_code,
        quantity=quantity,
        occurred_at=occurred_at or datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 5, 5, 11, 5, tzinfo=UTC),
        sale_kind="coffee",
        price=price,
    )


def _session_view(
    *,
    session_id: str = _SESSION_ID,
    period_ids: tuple[str, ...] = (_PERIOD_ID, _PERIOD_SIBLING),
    residual_by_sku: dict[str, Decimal] | None = None,
    technician_id: str | None = None,
) -> ResidualSessionView:
    if residual_by_sku is None:
        residual_by_sku = {_SKU: Decimal("-10")}
    return ResidualSessionView(
        session_id=session_id,
        technician_id=technician_id if technician_id is not None else _TECHNICIAN_ID.value,
        anchor_at=_ANCHOR_AT,
        period_ids=period_ids,
        residual_by_sku=residual_by_sku,
    )


def _build_use_case(
    *,
    snapshot: ResponsibilityPeriodReconciliation | None = None,
    sales: tuple[MachineSale, ...] = (),
    unit_cost: Decimal | None = Decimal("10.00"),
    residual_reader: InMemoryResidualSessionReader | None = None,
    extra_snapshots: tuple[ResponsibilityPeriodReconciliation, ...] = (),
    catalog: InMemoryUnitCostCatalog | None = None,
    opex_params: OpExParamsPort | None = None,
    service_facts: ServiceFactCounter | None = None,
    zero_maintenance_alerter: ZeroMaintenanceAlerter | None = None,
    location_rent: LocationRentOccupancyPort | None = None,
    tax_enabled: bool = True,
) -> tuple[ComputePeriodPnl, InMemoryPeriodPnlStore, InMemoryResidualSessionReader]:
    snapshots = InMemoryPeriodSnapshotReader()
    if snapshot is not None:
        snapshots.save(snapshot)
    for extra in extra_snapshots:
        snapshots.save(extra)
    sales_reader = InMemoryMachineSalesWindowReader()
    for sale in sales:
        sales_reader.add(sale)
    if catalog is None:
        catalog = InMemoryUnitCostCatalog(_default=unit_cost)
    store = InMemoryPeriodPnlStore()
    reader = residual_reader if residual_reader is not None else InMemoryResidualSessionReader()
    if opex_params is None:
        opex_params = InMemoryOpExParamsPort.zeros()
    if service_facts is None:
        facts = InMemoryServiceFactCounter()
        facts.set_default(1)
        service_facts = facts
    if zero_maintenance_alerter is None:
        zero_maintenance_alerter = NoOpZeroMaintenanceAlerter()
    if location_rent is None:
        rent_port = InMemoryLocationRentOccupancyPort()
        machines_opened: dict[MachineId, datetime] = {_MACHINE_ID: _OPENED_AT}
        if snapshot is not None:
            machines_opened[snapshot.machine_id] = snapshot.opened_at
        for extra in extra_snapshots:
            machines_opened[extra.machine_id] = extra.opened_at
        for machine_id, opened in machines_opened.items():
            rent_port.set(
                machine_id,
                (_zero_rent_occupancy(machine_id=machine_id, opened_at=opened),),
            )
        location_rent = rent_port
    use_case = ComputePeriodPnl(
        snapshots=snapshots,
        sales=sales_reader,
        unit_cost_catalog=catalog,
        period_pnl_store=store,
        residual_sessions=reader,
        opex_params=opex_params,
        service_facts=service_facts,
        zero_maintenance_alerter=zero_maintenance_alerter,
        location_rent=location_rent,
        tax_enabled=tax_enabled,
    )
    return use_case, store, reader


def test_compute_period_pnl_coffee_complete_saves() -> None:
    sale = _sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3"))
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(),
        sales=(sale,),
        unit_cost=Decimal("10.00"),
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert isinstance(result, PeriodPnl)
    saved = store.get(make_pnl_id(_PERIOD_ID))
    assert saved is not None
    assert saved == result
    assert store.source_session_ids[make_pnl_id(_PERIOD_ID)] == _SESSION_ID
    assert saved.pnl_id == make_pnl_id(_PERIOD_ID)
    assert saved.slice_key == "full"
    assert saved.period_id == _PERIOD_ID
    assert saved.machine_id == _MACHINE_ID
    assert saved.opened_at == _OPENED_AT
    assert saved.closed_at == _CLOSED_AT
    assert saved.revenue == Decimal("150.00")
    # sales_total=3 * cost 10 = 30; physical=10+0-7=3 * 10 = 30
    assert saved.cogs_expected == Decimal("30.00")
    assert saved.cogs_actual == Decimal("30.00")
    assert saved.allocated_shortage == Decimal("0")
    assert saved.allocated_surplus == Decimal("0")
    assert not hasattr(saved, "unallocated_residual_by_sku")
    assert saved.opex_breakdown == empty_opex_breakdown()
    assert saved.opex == Decimal("0")
    assert saved.net_before_residual == saved.revenue - saved.cogs_actual
    assert saved.net_after_shortage == saved.net_before_residual - saved.allocated_shortage
    assert saved.warnings == ()
    for field_name in (
        "revenue",
        "cogs_expected",
        "cogs_actual",
        "allocated_shortage",
        "allocated_surplus",
        "opex",
        "net_before_residual",
        "net_after_shortage",
    ):
        value = getattr(saved, field_name)
        assert value == value.quantize(Decimal("0.01"))


def test_compute_period_pnl_missing_cost_fails() -> None:
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(),
        sales=(_sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3")),),
        unit_cost=None,
    )

    with pytest.raises(MissingUnitCostError):
        use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert store.get(make_pnl_id(_PERIOD_ID)) is None


def test_compute_period_pnl_missing_snapshot_fails() -> None:
    use_case, store, _reader = _build_use_case(snapshot=None)

    with pytest.raises(SnapshotNotFoundError):
        use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert store.get(make_pnl_id(_PERIOD_ID)) is None


def test_compute_period_pnl_incomplete_snapshot_fails() -> None:
    use_case, store, _reader = _build_use_case(snapshot=_snapshot(status="pending_sales"))

    with pytest.raises(IncompleteSnapshotError):
        use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert store.get(make_pnl_id(_PERIOD_ID)) is None


def test_compute_period_pnl_null_price_warning() -> None:
    sales = (
        _sale(source_id="sale-null", price=None, quantity=Decimal("2")),
        _sale(source_id="sale-priced", price=Decimal("40.00"), quantity=Decimal("1")),
    )
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(),
        sales=sales,
        unit_cost=Decimal("10.00"),
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.revenue == Decimal("40.00")
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert isinstance(warning, PnlWarning)
    assert warning.code == "null_price"
    assert warning.sku is None
    assert "1" in warning.message
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_negative_physical_qty_warning() -> None:
    lines = (
        ReconciliationLine(
            product_code=_SKU,
            actual_prev=Decimal("1"),
            actual=Decimal("5"),
            calculated=Decimal("0"),
            delta=Decimal("-4"),
            loads_total=Decimal("0"),
            sales_total=Decimal("0"),
        ),
    )
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(lines=lines),
        sales=(),
        unit_cost=Decimal("2.00"),
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.cogs_actual == Decimal("-8.00")
    assert any(w.code == "negative_physical_qty" and w.sku == _SKU for w in result.warnings)
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_allocates_residual_from_session() -> None:
    # residual -10 @ cost 2 → money_total=20; weights 3 and 1 → share current=15
    current = _snapshot(period_id=_PERIOD_ID, sales_total=Decimal("3"))
    sibling = _snapshot(
        period_id=_PERIOD_SIBLING,
        machine_id=MachineId("102"),
        sales_total=Decimal("1"),
    )
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_CLOSED_AT.date(), cost=Decimal("10.00"))
    catalog.set(_SKU, as_of=_ANCHOR_AT.date(), cost=Decimal("2.00"))
    reader = InMemoryResidualSessionReader()
    reader.add(_session_view(residual_by_sku={_SKU: Decimal("-10")}))
    sale = _sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3"))
    use_case, store, _reader = _build_use_case(
        snapshot=current,
        sales=(sale,),
        extra_snapshots=(sibling,),
        residual_reader=reader,
        catalog=catalog,
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.allocated_shortage == Decimal("15.00")
    assert result.allocated_surplus == Decimal("0")
    assert not hasattr(result, "unallocated_residual_by_sku")
    assert result.opex_breakdown == empty_opex_breakdown()
    assert result.net_after_shortage == round_money(
        result.net_before_residual - result.allocated_shortage
    )
    assert store.source_session_ids[make_pnl_id(_PERIOD_ID)] == _SESSION_ID
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_skips_residual_when_not_reconciled() -> None:
    reader = InMemoryResidualSessionReader()
    reader.add(_session_view())
    use_case, store, reader = _build_use_case(
        snapshot=_snapshot(reconciled=False),
        sales=(_sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3")),),
        residual_reader=reader,
        unit_cost=Decimal("10.00"),
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.allocated_shortage == Decimal("0")
    assert result.allocated_surplus == Decimal("0")
    assert reader.calls == []
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_zero_sessions_zeros_allocation() -> None:
    use_case, store, reader = _build_use_case(
        snapshot=_snapshot(reconciled=True),
        sales=(_sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3")),),
        unit_cost=Decimal("10.00"),
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.allocated_shortage == Decimal("0")
    assert result.allocated_surplus == Decimal("0")
    assert len(reader.calls) == 1
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_ambiguous_residual_session_fails() -> None:
    reader = InMemoryResidualSessionReader()
    reader.add(_session_view(session_id="sess-a"))
    reader.add(_session_view(session_id="sess-b"))
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(reconciled=True),
        sales=(_sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3")),),
        residual_reader=reader,
        unit_cost=Decimal("10.00"),
    )

    with pytest.raises(AmbiguousResidualSessionError):
        use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert store.get(make_pnl_id(_PERIOD_ID)) is None


def test_compute_period_pnl_source_session_mismatch_ignored() -> None:
    current = _snapshot(period_id=_PERIOD_ID, sales_total=Decimal("3"))
    sibling = _snapshot(
        period_id=_PERIOD_SIBLING,
        machine_id=MachineId("102"),
        sales_total=Decimal("1"),
    )
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_CLOSED_AT.date(), cost=Decimal("10.00"))
    catalog.set(_SKU, as_of=_ANCHOR_AT.date(), cost=Decimal("2.00"))
    reader = InMemoryResidualSessionReader()
    reader.add(_session_view(session_id="sess-found", residual_by_sku={_SKU: Decimal("-10")}))
    sale = _sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3"))
    use_case, store, _reader = _build_use_case(
        snapshot=current,
        sales=(sale,),
        extra_snapshots=(sibling,),
        residual_reader=reader,
        catalog=catalog,
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id="sess-other")

    assert result.allocated_shortage == Decimal("15.00")
    assert all("mismatch" not in w.message.lower() for w in result.warnings)
    assert all(w.code != "source_session_mismatch" for w in result.warnings)
    assert store.source_session_ids[make_pnl_id(_PERIOD_ID)] == "sess-other"


def test_compute_period_pnl_surplus_warning_not_in_net() -> None:
    current = _snapshot(period_id=_PERIOD_ID, sales_total=Decimal("3"))
    sibling = _snapshot(
        period_id=_PERIOD_SIBLING,
        machine_id=MachineId("102"),
        sales_total=Decimal("1"),
    )
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_CLOSED_AT.date(), cost=Decimal("10.00"))
    catalog.set(_SKU, as_of=_ANCHOR_AT.date(), cost=Decimal("2.00"))
    # residual +10 @ cost 2 → money_total=20; share current = 15 surplus
    reader = InMemoryResidualSessionReader()
    reader.add(_session_view(residual_by_sku={_SKU: Decimal("10")}))
    sale = _sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3"))
    use_case, store, _reader = _build_use_case(
        snapshot=current,
        sales=(sale,),
        extra_snapshots=(sibling,),
        residual_reader=reader,
        catalog=catalog,
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.allocated_surplus == Decimal("15.00")
    assert result.allocated_shortage == Decimal("0")
    assert not hasattr(result, "unallocated_residual_by_sku")
    assert result.opex_breakdown == empty_opex_breakdown()
    assert result.net_after_shortage == result.net_before_residual
    surplus_warnings = [w for w in result.warnings if w.code == "allocated_surplus_nonzero"]
    assert len(surplus_warnings) == 1
    assert surplus_warnings[0].sku is None
    assert "15.00" in surplus_warnings[0].message
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_same_catalog_for_cogs_and_residual() -> None:
    current = _snapshot(period_id=_PERIOD_ID, sales_total=Decimal("3"))
    sibling = _snapshot(
        period_id=_PERIOD_SIBLING,
        machine_id=MachineId("102"),
        sales_total=Decimal("1"),
    )
    base = InMemoryUnitCostCatalog()
    base.set(_SKU, as_of=_CLOSED_AT.date(), cost=Decimal("10.00"))
    base.set(_SKU, as_of=_ANCHOR_AT.date(), cost=Decimal("2.00"))

    as_of_calls: list[object] = []
    catalog_ids: list[int] = []

    class _TrackingCatalog:
        def get(self, product_code: str, *, as_of: object) -> Decimal | None:
            catalog_ids.append(id(self))
            as_of_calls.append(as_of)
            return base.get(product_code, as_of=as_of)  # type: ignore[arg-type]

    tracking = _TrackingCatalog()
    reader = InMemoryResidualSessionReader()
    reader.add(_session_view(residual_by_sku={_SKU: Decimal("-10")}))
    sale = _sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3"))
    use_case, store, _reader = _build_use_case(
        snapshot=current,
        sales=(sale,),
        extra_snapshots=(sibling,),
        residual_reader=reader,
        catalog=tracking,  # type: ignore[arg-type]
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.allocated_shortage == Decimal("15.00")
    assert len(set(catalog_ids)) == 1
    assert _CLOSED_AT.date() in as_of_calls
    assert _ANCHOR_AT.date() in as_of_calls
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_fills_opex_and_nets() -> None:
    sale = _sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3"))
    catalog = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=_MACHINE_ID,
                valid_from=date(2026, 1, 1),
                rent_monthly=Decimal("310"),
                rent_percent=None,
                duty_mode="patent",
                patent_monthly=Decimal("0"),
                tax_percent=None,
                acquiring_percent=Decimal("0"),
                acquiring_fee_per_sale=Decimal("0"),
                terminal_monthly=Decimal("0"),
            ),
        ),
        labor_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("50")),),
        terminal_global_rows=(),
    )
    counter = InMemoryServiceFactCounter()
    counter.set_count(_MACHINE_ID, opened_at=_OPENED_AT, closed_at=_CLOSED_AT, count=2)
    alerter = RecordingZeroMaintenanceAlerter()
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(),
        sales=(sale,),
        unit_cost=Decimal("10.00"),
        opex_params=catalog,
        service_facts=counter,
        zero_maintenance_alerter=alerter,
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.opex > Decimal("0")
    breakdown = dict(result.opex_breakdown)
    assert tuple(breakdown) == OPEX_BREAKDOWN_KEYS
    assert breakdown["route_fuel"] == Decimal("0.00")
    assert result.net_before_residual == round_money(
        result.revenue - result.cogs_actual - result.opex
    )
    assert alerter.calls == []
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_tax_known_not_in_nets() -> None:
    sale = _sale(source_id="sale-1", price=Decimal("100.00"), quantity=Decimal("1"))
    catalog = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=_MACHINE_ID,
                valid_from=date(2026, 1, 1),
                rent_monthly=Decimal("0"),
                rent_percent=None,
                duty_mode="tax",
                patent_monthly=None,
                tax_percent=Decimal("10"),
                acquiring_percent=Decimal("0"),
                acquiring_fee_per_sale=Decimal("0"),
                terminal_monthly=Decimal("0"),
            ),
        ),
        labor_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("0")),),
        terminal_global_rows=(),
    )
    counter = InMemoryServiceFactCounter()
    counter.set_count(_MACHINE_ID, opened_at=_OPENED_AT, closed_at=_CLOSED_AT, count=1)
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(),
        sales=(sale,),
        unit_cost=Decimal("1.00"),
        opex_params=catalog,
        service_facts=counter,
        zero_maintenance_alerter=RecordingZeroMaintenanceAlerter(),
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    tax = dict(result.opex_breakdown)["tax"]
    assert tax == round_money(Decimal("10") / Decimal("100") * result.revenue)
    assert result.opex == Decimal("0.00")
    assert result.net_before_residual == round_money(
        result.revenue - result.cogs_actual - result.opex
    )
    assert result.net_before_residual == round_money(
        result.revenue - result.cogs_actual
    )  # tax not subtracted
    assert not any(w.code == "tax_pending_manual" for w in result.warnings)
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_tax_disabled_pending_ignores_percent() -> None:
    sale = _sale(source_id="sale-1", price=Decimal("100.00"), quantity=Decimal("1"))
    catalog = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=_MACHINE_ID,
                valid_from=date(2026, 1, 1),
                rent_monthly=Decimal("0"),
                rent_percent=None,
                duty_mode="tax",
                patent_monthly=None,
                tax_percent=Decimal("10"),
                acquiring_percent=Decimal("0"),
                acquiring_fee_per_sale=Decimal("0"),
                terminal_monthly=Decimal("0"),
            ),
        ),
        labor_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("0")),),
        terminal_global_rows=(),
    )
    counter = InMemoryServiceFactCounter()
    counter.set_count(_MACHINE_ID, opened_at=_OPENED_AT, closed_at=_CLOSED_AT, count=1)
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(),
        sales=(sale,),
        unit_cost=Decimal("1.00"),
        opex_params=catalog,
        service_facts=counter,
        zero_maintenance_alerter=RecordingZeroMaintenanceAlerter(),
        tax_enabled=False,
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert dict(result.opex_breakdown)["tax"] is None
    assert any(w.code == "tax_pending_manual" for w in result.warnings)
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None


def test_compute_period_pnl_zero_maintenance_persists_and_alerts() -> None:
    counter = InMemoryServiceFactCounter()
    counter.set_count(_MACHINE_ID, opened_at=_OPENED_AT, closed_at=_CLOSED_AT, count=0)
    alerter = RecordingZeroMaintenanceAlerter()
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(),
        sales=(_sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3")),),
        unit_cost=Decimal("10.00"),
        service_facts=counter,
        zero_maintenance_alerter=alerter,
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert isinstance(result, PeriodPnl)
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None
    assert dict(result.opex_breakdown)["labor"] == Decimal("0.00")
    assert any(w.code == "zero_maintenance_in_period" for w in result.warnings)
    assert len(alerter.calls) == 1
    call = alerter.calls[0]
    assert call.period_id == _PERIOD_ID
    assert call.machine_id == _MACHINE_ID
    assert call.maintenance_count == 0


def test_compute_period_pnl_zero_maintenance_alerter_noop() -> None:
    counter = InMemoryServiceFactCounter()
    counter.set_count(_MACHINE_ID, opened_at=_OPENED_AT, closed_at=_CLOSED_AT, count=0)
    use_case, store, _reader = _build_use_case(
        snapshot=_snapshot(),
        sales=(_sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3")),),
        unit_cost=Decimal("10.00"),
        service_facts=counter,
        zero_maintenance_alerter=NoOpZeroMaintenanceAlerter(),
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert store.get(make_pnl_id(_PERIOD_ID)) is not None
    assert any(w.code == "zero_maintenance_in_period" for w in result.warnings)
    assert isinstance(result, PeriodPnl)


def test_compute_period_pnl_residual_regression_no_unallocated_field() -> None:
    # residual -10 @ cost 2 → money_total=20; weights 3 and 1 → share current=15
    current = _snapshot(period_id=_PERIOD_ID, sales_total=Decimal("3"))
    sibling = _snapshot(
        period_id=_PERIOD_SIBLING,
        machine_id=MachineId("102"),
        sales_total=Decimal("1"),
    )
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_CLOSED_AT.date(), cost=Decimal("10.00"))
    catalog.set(_SKU, as_of=_ANCHOR_AT.date(), cost=Decimal("2.00"))
    reader = InMemoryResidualSessionReader()
    reader.add(_session_view(residual_by_sku={_SKU: Decimal("-10")}))
    sale = _sale(source_id="sale-1", price=Decimal("50.00"), quantity=Decimal("3"))
    use_case, store, _reader = _build_use_case(
        snapshot=current,
        sales=(sale,),
        extra_snapshots=(sibling,),
        residual_reader=reader,
        catalog=catalog,
    )

    result = use_case.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)

    assert result.allocated_shortage == Decimal("15.00")
    assert not hasattr(result, "unallocated_residual_by_sku")
    assert result.opex_breakdown is not None
    assert len(result.opex_breakdown) > 0
    assert store.get(make_pnl_id(_PERIOD_ID)) is not None
