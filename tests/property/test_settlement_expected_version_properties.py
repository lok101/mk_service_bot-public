from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from src.domain.ids import AccountabilityId, EventId, MachineId, TechnicianId
from src.domain.technician_settlement.events import PeriodAccountabilityRecorded
from src.infrastructure.mongodb.errors import EventStoreConcurrencyError
from src.infrastructure.testing.settlement_fakes import InMemoryTechnicianSettlementEventStore

_TECH = TechnicianId("tech-prop")
_CLOSED = datetime(2026, 5, 1, tzinfo=UTC)


def _accountability(*, event_id: str, period_id: str) -> PeriodAccountabilityRecorded:
    return PeriodAccountabilityRecorded(
        event_id=EventId(event_id),
        accountability_id=AccountabilityId(f"{_TECH.value}:{period_id}"),
        technician_id=_TECH,
        period_id=period_id,
        machine_id=MachineId("vm-prop"),
        delta_by_sku={"coffee": Decimal("-1")},
        closed_at=_CLOSED,
        occurred_at=_CLOSED,
    )


@given(history_size=st.integers(min_value=1, max_value=20))
@example(history_size=1)
@settings(max_examples=50)
def test_stale_settlement_decision_never_gets_renumbered(history_size: int) -> None:
    store = InMemoryTechnicianSettlementEventStore()
    for index in range(history_size):
        store.append(
            _accountability(event_id=f"evt-hist-{index}", period_id=f"p{index}"),
            expected_version=index,
        )

    before_ids = [event.event_id.value for event in store.get_events_for_technician(_TECH)]
    stale = _accountability(event_id="evt-stale-distinct", period_id="stale")

    with pytest.raises(EventStoreConcurrencyError):
        store.append(stale, expected_version=history_size - 1)

    after_ids = [event.event_id.value for event in store.get_events_for_technician(_TECH)]
    assert after_ids == before_ids
    assert "evt-stale-distinct" not in after_ids
