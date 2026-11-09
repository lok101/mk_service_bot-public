from __future__ import annotations

from src.application.machine_pnl.models import make_pnl_id


def test_period_pnl_default_pnl_id_full_slice() -> None:
    assert make_pnl_id("period-1") == "pnl:period-1:full"
    assert make_pnl_id("period-1", slice_key="full") == "pnl:period-1:full"
