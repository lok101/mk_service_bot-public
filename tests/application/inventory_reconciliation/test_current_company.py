from __future__ import annotations

from datetime import UTC, datetime

from src.application.inventory_reconciliation.company_occupancy import MachineCompanyOccupancy
from src.application.inventory_reconciliation.current_company import (
    open_company_id,
    resolve_current_company_name,
)
from src.domain.ids import MachineId

_MID = MachineId("vm-01")
_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_T1 = datetime(2026, 2, 1, tzinfo=UTC)


def test_open_company_id_returns_open_interval() -> None:
    intervals = (
        MachineCompanyOccupancy(_MID, 1, _T0, _T1),
        MachineCompanyOccupancy(_MID, 2, _T1, None),
    )
    assert open_company_id(intervals) == 2


def test_open_company_id_none_when_no_open() -> None:
    intervals = (MachineCompanyOccupancy(_MID, 1, _T0, _T1),)
    assert open_company_id(intervals) is None


def test_open_company_id_picks_max_valid_from() -> None:
    # дефект данных: два open — берём max valid_from, без raise
    intervals = (
        MachineCompanyOccupancy(_MID, 9, _T0, None),
        MachineCompanyOccupancy(_MID, 3, _T1, None),
    )
    assert open_company_id(intervals) == 3


def test_resolve_current_company_name_happy() -> None:
    intervals = (MachineCompanyOccupancy(_MID, 7, _T0, None),)
    assert resolve_current_company_name(intervals, {7: "Орлов М.О."}) == "Орлов М.О."


def test_resolve_current_company_name_empty_when_no_open() -> None:
    assert resolve_current_company_name((), {1: "X"}) == ""


def test_resolve_current_company_name_empty_when_name_missing() -> None:
    intervals = (MachineCompanyOccupancy(_MID, 7, _T0, None),)
    assert resolve_current_company_name(intervals, {7: ""}) == ""
    assert resolve_current_company_name(intervals, {}) == ""
