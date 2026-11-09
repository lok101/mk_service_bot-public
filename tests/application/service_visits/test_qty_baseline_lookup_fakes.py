from __future__ import annotations

from datetime import date
from decimal import Decimal

from tests.application.service_visits.qty_baseline_lookup_fakes import (
    FakeMachineSalesQtyBaselineLookup,
)

from src.application.service_visits.null_qty_baseline_lookup import (
    NullMachineSalesQtyBaselineLookup,
)
from src.application.service_visits.ports import MachineSalesQtyBaselineLookup
from src.domain.ids import MachineId

_MACHINE = MachineId("101")
_DAY = date(2026, 8, 12)


def test_null_qty_baseline_lookup_is_protocol_instance() -> None:
    lookup: MachineSalesQtyBaselineLookup = NullMachineSalesQtyBaselineLookup()
    assert isinstance(lookup, MachineSalesQtyBaselineLookup)


def test_null_qty_baseline_lookup_returns_none() -> None:
    lookup = NullMachineSalesQtyBaselineLookup()
    assert lookup.baseline_avg_qty(machine_id=_MACHINE, as_of_day=_DAY) is None


def test_fake_qty_baseline_lookup_returns_configured_avg() -> None:
    lookup = FakeMachineSalesQtyBaselineLookup(result=Decimal("40"))
    assert lookup.baseline_avg_qty(machine_id=_MACHINE, as_of_day=_DAY) == Decimal("40")
    assert lookup.calls == [(_MACHINE, _DAY)]
