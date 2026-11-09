from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations import MachineOperations
from src.domain.machine_operations.events import LoadingSubmitted

_MACHINE = MachineId("vm-last-load")
_TECH = TechnicianId("tech-1")
_T0 = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)
_T2 = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)


def _loading(
    *,
    event_id: str,
    submitted_at: datetime,
) -> LoadingSubmitted:
    return LoadingSubmitted(
        event_id=EventId(event_id),
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=submitted_at,
        occurred_at=submitted_at,
        form_id="form-load",
        form_token=f"tok-{event_id}",
    )


def test_rehydrate_loading_sets_last_loading_submitted_at() -> None:
    aggregate = MachineOperations.rehydrate(
        _MACHINE,
        [_loading(event_id="l1", submitted_at=_T1)],
    )
    assert aggregate.last_loading_submitted_at() == _T1


def test_rehydrate_last_loading_uses_max_submitted_at_across_loadings() -> None:
    events = [
        _loading(event_id="l1", submitted_at=_T0),
        _loading(event_id="l2", submitted_at=_T2),
        _loading(event_id="l3", submitted_at=_T1),
    ]
    aggregate = MachineOperations.rehydrate(_MACHINE, events)
    assert aggregate.last_loading_submitted_at() == _T2
