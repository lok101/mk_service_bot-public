from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.memory import InMemoryEventStore
from src.infrastructure.mongodb.errors import EventStoreConcurrencyError

_MACHINE_ID = MachineId("vm-prop-01")
_TECH = TechnicianId("tech-a")
_COMPLETED_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)


def _revision(*, event_id: str) -> RevisionCompleted:
    return RevisionCompleted(
        event_id=EventId(event_id),
        revision_id=RevisionId(f"rev-{event_id}"),
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        completed_at=_COMPLETED_AT,
        occurred_at=_COMPLETED_AT,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-prop",
        form_token=f"token-{event_id}",
    )


@given(history_size=st.integers(min_value=0, max_value=20))
@example(history_size=1)
@settings(max_examples=50)
def test_store_never_renumbers_stale_machine_event(history_size: int) -> None:
    store = InMemoryEventStore()
    for index in range(history_size):
        store.append(
            _revision(event_id=f"evt-hist-{index}"),
            expected_version=index,
        )

    before_ids = [event.event_id.value for event in store.get_events_for_machine(_MACHINE_ID)]
    stale = _revision(event_id="evt-stale-distinct")

    if history_size == 0:
        with pytest.raises(ValueError, match="expected_version must be non-negative"):
            store.append(stale, expected_version=-1)
    else:
        with pytest.raises(EventStoreConcurrencyError):
            store.append(stale, expected_version=history_size - 1)

    after_ids = [event.event_id.value for event in store.get_events_for_machine(_MACHINE_ID)]
    assert after_ids == before_ids
    assert "evt-stale-distinct" not in after_ids
