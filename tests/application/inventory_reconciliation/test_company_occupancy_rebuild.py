from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancy,
    rebuild_company_occupancy,
)
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale

_MACHINE = MachineId("vm-01")
_T1 = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_T2 = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
_T3 = datetime(2026, 6, 20, 8, 0, tzinfo=UTC)
_INGESTED = datetime(2026, 7, 1, tzinfo=UTC)


def _sale(
    *,
    source_id: str,
    occurred_at: datetime,
    company_id: int | None,
) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=_MACHINE,
        product_code="2301",
        quantity=Decimal("1"),
        occurred_at=occurred_at,
        ingested_at=_INGESTED,
        sale_kind="coffee",
        company_id=company_id,
    )


def test_rebuild_splits_interval_on_company_change() -> None:
    intervals = rebuild_company_occupancy(
        _MACHINE,
        (
            _sale(source_id="a", occurred_at=_T1, company_id=1),
            _sale(source_id="b", occurred_at=_T2, company_id=1),
            _sale(source_id="c", occurred_at=_T3, company_id=2),
        ),
    )
    assert intervals == (
        MachineCompanyOccupancy(
            machine_id=_MACHINE,
            company_id=1,
            valid_from=_T1,
            valid_to=_T3,
        ),
        MachineCompanyOccupancy(
            machine_id=_MACHINE,
            company_id=2,
            valid_from=_T3,
            valid_to=None,
        ),
    )


def test_rebuild_ignores_sales_without_company_id() -> None:
    intervals = rebuild_company_occupancy(
        _MACHINE,
        (
            _sale(source_id="a", occurred_at=_T1, company_id=1),
            _sale(source_id="gap", occurred_at=_T2, company_id=None),
            _sale(source_id="b", occurred_at=_T3, company_id=1),
        ),
    )
    assert intervals == (
        MachineCompanyOccupancy(
            machine_id=_MACHINE,
            company_id=1,
            valid_from=_T1,
            valid_to=None,
        ),
    )


def test_rebuild_late_arrival_merges_into_existing_interval() -> None:
    intervals = rebuild_company_occupancy(
        _MACHINE,
        (
            _sale(source_id="new", occurred_at=_T3, company_id=2),
            _sale(source_id="old-late", occurred_at=_T1, company_id=1),
            _sale(source_id="mid", occurred_at=_T2, company_id=1),
        ),
    )
    assert intervals == (
        MachineCompanyOccupancy(
            machine_id=_MACHINE,
            company_id=1,
            valid_from=_T1,
            valid_to=_T3,
        ),
        MachineCompanyOccupancy(
            machine_id=_MACHINE,
            company_id=2,
            valid_from=_T3,
            valid_to=None,
        ),
    )


def test_rebuild_same_timestamp_different_company_drops_zero_length() -> None:
    intervals = rebuild_company_occupancy(
        _MACHINE,
        (
            _sale(source_id="a", occurred_at=_T1, company_id=1),
            _sale(source_id="b", occurred_at=_T1, company_id=2),
        ),
    )
    assert intervals == (
        MachineCompanyOccupancy(
            machine_id=_MACHINE,
            company_id=2,
            valid_from=_T1,
            valid_to=None,
        ),
    )


def test_rebuild_empty_when_no_company_ids() -> None:
    intervals = rebuild_company_occupancy(
        _MACHINE,
        (_sale(source_id="a", occurred_at=_T1, company_id=None),),
    )
    assert intervals == ()


def test_in_memory_occupancy_store_replace_lists_and_isolates_machines() -> None:
    from src.infrastructure.testing.company_occupancy_fakes import (
        InMemoryMachineCompanyOccupancyStore,
    )

    store = InMemoryMachineCompanyOccupancyStore()
    first = (
        MachineCompanyOccupancy(
            machine_id=_MACHINE,
            company_id=1,
            valid_from=_T1,
            valid_to=None,
        ),
    )
    store.replace_for_machine(_MACHINE, first)
    other = MachineId("vm-02")
    store.replace_for_machine(
        other,
        (
            MachineCompanyOccupancy(
                machine_id=other,
                company_id=9,
                valid_from=_T2,
                valid_to=None,
            ),
        ),
    )
    store.replace_for_machine(_MACHINE, ())
    assert store.list_for_machine(_MACHINE) == ()
    assert store.list_for_machine(other)[0].company_id == 9
