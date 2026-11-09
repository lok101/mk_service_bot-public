from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.machine_pnl.errors import RentTermsPending
from src.application.machine_pnl.money import round_money
from src.application.machine_pnl.rent_ports import FixtureLocationRentCatalog
from src.application.machine_pnl.rent_slices import (
    LocationRentOccupancy,
    sum_rent_slices,
)
from src.domain.ids import MachineId

_MACHINE_ID = MachineId("101")


def test_sum_rent_slices_prorata_and_percent() -> None:
    opened = datetime(2026, 5, 1, 10, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, tzinfo=UTC)  # period_days=10; May=31
    occ = LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE_ID,
        installed_at=opened,
        removed_at=None,
        rent_monthly=Decimal("310"),
        rent_percent=Decimal("10"),
    )
    result = sum_rent_slices(
        occupancies=(occ,),
        opened_at=opened,
        closed_at=closed,
        revenue=Decimal("100"),
    )
    assert result.rent_fixed == round_money(Decimal("310") * Decimal("10") / Decimal("31"))
    assert result.rent_fixed == Decimal("100.00")
    assert result.rent_percent == Decimal("10.00")


def test_sum_rent_slices_two_halves_sum_fixed() -> None:
    opened = datetime(2026, 5, 1, 10, tzinfo=UTC)
    mid = datetime(2026, 5, 6, 10, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, tzinfo=UTC)  # period_days=10
    occ_a = LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE_ID,
        installed_at=opened,
        removed_at=mid,
        rent_monthly=Decimal("310"),
        rent_percent=None,
    )
    occ_b = LocationRentOccupancy(
        location_id="loc-b",
        machine_id=_MACHINE_ID,
        installed_at=mid,
        removed_at=None,
        rent_monthly=Decimal("310"),
        rent_percent=None,
    )
    result = sum_rent_slices(
        occupancies=(occ_a, occ_b),
        opened_at=opened,
        closed_at=closed,
        revenue=Decimal("0"),
    )
    # days_a = 5 (May1→May6), days_b = 5 (May6→May11)
    expected_a = round_money(Decimal("310") * Decimal("5") / Decimal("31"))
    expected_b = round_money(Decimal("310") * Decimal("5") / Decimal("31"))
    assert result.rent_fixed == round_money(expected_a + expected_b)
    assert result.rent_percent == Decimal("0.00")


def test_sum_rent_slices_empty_rent_monthly_raises() -> None:
    opened = datetime(2026, 5, 1, 10, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, tzinfo=UTC)
    occ = LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE_ID,
        installed_at=opened,
        removed_at=None,
        rent_monthly=None,
        rent_percent=None,
    )
    with pytest.raises(RentTermsPending):
        sum_rent_slices(
            occupancies=(occ,),
            opened_at=opened,
            closed_at=closed,
            revenue=Decimal("0"),
        )


def test_sum_rent_slices_no_intersection_raises() -> None:
    opened = datetime(2026, 5, 1, 10, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, tzinfo=UTC)
    occ = LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE_ID,
        installed_at=datetime(2026, 4, 1, 10, tzinfo=UTC),
        removed_at=datetime(2026, 4, 15, 10, tzinfo=UTC),
        rent_monthly=Decimal("310"),
        rent_percent=None,
    )
    with pytest.raises(RentTermsPending):
        sum_rent_slices(
            occupancies=(occ,),
            opened_at=opened,
            closed_at=closed,
            revenue=Decimal("0"),
        )


def test_sum_rent_slices_empty_occupancies_raises() -> None:
    opened = datetime(2026, 5, 1, 10, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, tzinfo=UTC)
    with pytest.raises(RentTermsPending):
        sum_rent_slices(
            occupancies=(),
            opened_at=opened,
            closed_at=closed,
            revenue=Decimal("0"),
        )


def test_sum_rent_slices_explicit_zero_ok() -> None:
    opened = datetime(2026, 5, 1, 10, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, tzinfo=UTC)
    occ = LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE_ID,
        installed_at=opened,
        removed_at=None,
        rent_monthly=Decimal("0"),
        rent_percent=None,
    )
    result = sum_rent_slices(
        occupancies=(occ,),
        opened_at=opened,
        closed_at=closed,
        revenue=Decimal("100"),
    )
    assert result.rent_fixed == Decimal("0.00")
    assert result.rent_percent == Decimal("0.00")


def test_fixture_location_rent_catalog_filters_by_machine() -> None:
    opened = datetime(2026, 5, 1, 10, tzinfo=UTC)
    occ_101 = LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE_ID,
        installed_at=opened,
        removed_at=None,
        rent_monthly=Decimal("0"),
        rent_percent=None,
    )
    occ_other = LocationRentOccupancy(
        location_id="loc-b",
        machine_id=MachineId("999"),
        installed_at=opened,
        removed_at=None,
        rent_monthly=Decimal("100"),
        rent_percent=None,
    )
    catalog = FixtureLocationRentCatalog(occupancies=(occ_101, occ_other))
    assert catalog.list_for_machine(_MACHINE_ID) == (occ_101,)
    assert catalog.list_for_machine(MachineId("999")) == (occ_other,)
    assert catalog.list_for_machine(MachineId("000")) == ()
