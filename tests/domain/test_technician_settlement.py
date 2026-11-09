from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import AccountabilityId, MachineId, TechnicianId
from src.domain.technician_settlement.aggregate import (
    RecordPeriodAccountability,
    TechnicianSettlement,
)
from src.domain.technician_settlement.events import PeriodAccountabilityRecorded


def _record(period_id: str, delta: dict[str, Decimal]) -> RecordPeriodAccountability:
    return RecordPeriodAccountability(
        accountability_id=AccountabilityId(f"tech-a:{period_id}"),
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        delta_by_sku=delta,
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


def test_record_accountability_emits_event_and_updates_balance() -> None:
    aggregate = TechnicianSettlement.empty(TechnicianId("tech-a"))
    event = aggregate.record_period_accountability(
        _record("p1", {"coffee": Decimal("-2"), "water": Decimal("1")}),
    )
    assert isinstance(event, PeriodAccountabilityRecorded)
    assert aggregate.net_balance_by_sku()["coffee"] == Decimal("-2")
    assert len(aggregate.collect_events()) == 1


def test_record_accountability_idempotent_by_accountability_id() -> None:
    aggregate = TechnicianSettlement.empty(TechnicianId("tech-a"))
    first = aggregate.record_period_accountability(_record("p1", {"coffee": Decimal("-2")}))
    second = aggregate.record_period_accountability(_record("p1", {"coffee": Decimal("-2")}))
    assert first is not None
    assert second is not None
    assert second.event_id == first.event_id
    assert len(aggregate.collect_events()) == 1
    assert aggregate.net_balance_by_sku()["coffee"] == Decimal("-2")


def test_rehydrate_replays_balance() -> None:
    aggregate = TechnicianSettlement.empty(TechnicianId("tech-a"))
    event = aggregate.record_period_accountability(_record("p1", {"coffee": Decimal("-2")}))
    assert event is not None
    replayed = TechnicianSettlement.rehydrate(TechnicianId("tech-a"), [event])
    assert replayed.net_balance_by_sku() == aggregate.net_balance_by_sku()
    assert replayed.collect_events() == []
