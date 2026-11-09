from __future__ import annotations

from datetime import UTC, datetime

from tests.application.machine_pnl.fakes import InMemoryServiceFactCounter

from src.domain.ids import MachineId


def test_service_fact_counter_fake_count() -> None:
    counter = InMemoryServiceFactCounter()
    mid = MachineId("101")
    opened = datetime(2026, 5, 1, tzinfo=UTC)
    closed = datetime(2026, 5, 10, tzinfo=UTC)
    counter.set_count(mid, opened_at=opened, closed_at=closed, count=2)
    assert counter.count_completed(mid, opened_at=opened, closed_at=closed) == 2
