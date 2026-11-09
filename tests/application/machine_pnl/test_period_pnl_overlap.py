from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.machine_pnl.fakes import InMemoryPeriodPnlStore

from src.application.machine_pnl.models import FULL_SLICE_KEY, PeriodPnl, make_pnl_id
from src.application.machine_pnl.opex_breakdown import empty_opex_breakdown
from src.domain.ids import MachineId

_MACHINE = MachineId("101")
_OTHER = MachineId("102")


def _pnl(
    *,
    period_id: str,
    machine_id: MachineId = _MACHINE,
    opened_at: datetime,
    closed_at: datetime,
) -> PeriodPnl:
    return PeriodPnl(
        pnl_id=make_pnl_id(period_id),
        period_id=period_id,
        slice_key=FULL_SLICE_KEY,
        machine_id=machine_id,
        opened_at=opened_at,
        closed_at=closed_at,
        revenue=Decimal("0.00"),
        cogs_expected=Decimal("0.00"),
        cogs_actual=Decimal("0.00"),
        allocated_shortage=Decimal("0.00"),
        allocated_surplus=Decimal("0.00"),
        opex=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        net_before_residual=Decimal("0.00"),
        net_after_shortage=Decimal("0.00"),
        warnings=(),
    )


def test_list_overlapping_includes_crossing_period() -> None:
    store = InMemoryPeriodPnlStore()
    crossing = _pnl(
        period_id="cross",
        opened_at=datetime(2026, 5, 20, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    store.save(crossing, source_session_id=None)
    found = store.list_overlapping(
        _MACHINE,
        range_start=datetime(2026, 6, 1, tzinfo=UTC),
        range_end=datetime(2026, 7, 1, tzinfo=UTC),
    )
    assert [p.period_id for p in found] == ["cross"]


def test_list_overlapping_excludes_non_overlapping() -> None:
    store = InMemoryPeriodPnlStore()
    before = _pnl(
        period_id="before",
        opened_at=datetime(2026, 4, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    other_machine = _pnl(
        period_id="other",
        machine_id=_OTHER,
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 15, tzinfo=UTC),
    )
    store.save(before, source_session_id=None)
    store.save(other_machine, source_session_id=None)
    found = store.list_overlapping(
        _MACHINE,
        range_start=datetime(2026, 6, 1, tzinfo=UTC),
        range_end=datetime(2026, 7, 1, tzinfo=UTC),
    )
    assert found == ()


def test_list_for_machine_returns_all_for_machine() -> None:
    store = InMemoryPeriodPnlStore()
    a = _pnl(
        period_id="a",
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
    )
    other = _pnl(
        period_id="other",
        machine_id=_OTHER,
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
    )
    store.save(a, source_session_id=None)
    store.save(other, source_session_id=None)
    found = store.list_for_machine(_MACHINE)
    assert [p.period_id for p in found] == ["a"]
