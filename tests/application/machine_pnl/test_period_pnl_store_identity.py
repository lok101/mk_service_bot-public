from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.machine_pnl.fakes import InMemoryPeriodPnlStore

from src.application.machine_pnl.models import (
    FULL_SLICE_KEY,
    PeriodPnl,
    make_pnl_id,
)
from src.application.machine_pnl.opex_breakdown import empty_opex_breakdown
from src.domain.ids import MachineId


def _minimal_pnl(
    *,
    period_id: str = "p-1",
    slice_key: str = FULL_SLICE_KEY,
) -> PeriodPnl:
    return PeriodPnl(
        pnl_id=make_pnl_id(period_id, slice_key=slice_key),
        period_id=period_id,
        slice_key=slice_key,
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        closed_at=datetime(2026, 1, 10, tzinfo=UTC),
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


def test_period_pnl_store_upsert_by_pnl_id() -> None:
    store = InMemoryPeriodPnlStore()
    pnl = _minimal_pnl(period_id="p-1", slice_key=FULL_SLICE_KEY)
    store.save(pnl, source_session_id="s1")
    loaded = store.get(pnl.pnl_id)
    assert loaded is not None
    assert loaded.pnl_id == make_pnl_id("p-1")
    assert loaded.slice_key == "full"


def test_period_pnl_store_list_by_period_id() -> None:
    store = InMemoryPeriodPnlStore()
    store.save(_minimal_pnl(period_id="p-1"), source_session_id=None)
    rows = store.list_by_period_id("p-1")
    assert len(rows) == 1
    assert rows[0].pnl_id == make_pnl_id("p-1")
