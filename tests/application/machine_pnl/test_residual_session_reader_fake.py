from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.machine_pnl.fakes import InMemoryResidualSessionReader

from src.application.machine_pnl.residual_ports import ResidualSessionView
from src.domain.ids import TechnicianId


def test_residual_session_reader_fake_find_containing() -> None:
    reader = InMemoryResidualSessionReader()
    view = ResidualSessionView(
        session_id="s1",
        technician_id="tech-1",
        anchor_at=datetime(2026, 5, 15, tzinfo=UTC),
        period_ids=("p1", "p2"),
        residual_by_sku={"sku": Decimal("-1")},
    )
    reader.add(view)
    found = reader.find_completed_containing("p1", technician_id=TechnicianId("tech-1"))
    assert found == (view,)
    assert reader.find_completed_containing("p1", technician_id=TechnicianId("other")) == ()
    assert reader.find_completed_containing("missing", technician_id=TechnicianId("tech-1")) == ()
