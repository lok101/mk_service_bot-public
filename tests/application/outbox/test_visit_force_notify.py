from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.application.outbox.visit_force_notify import VisitForceNotifyHandler
from src.application.service_visits import IncidentSource, VisitForceOutcome
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.service_visits import (
    ServiceVisitForceNotifyRequested,
    visit_force_notify_event_id,
)


@dataclass
class _FakeTg:
    sent: list[tuple[int, str]] = field(default_factory=list)
    fail: bool = False

    async def send_message(self, *, chat_id: int, text: str) -> None:
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))


def _event(*, telegram_user_id: int | None = 42) -> ServiceVisitForceNotifyRequested:
    return ServiceVisitForceNotifyRequested(
        event_id=EventId(visit_force_notify_event_id("extra:101", "g1")),
        visit_id="extra:101",
        machine_id=MachineId("101"),
        technician_id=TechnicianId("t1"),
        technician_display="Иван",
        telegram_user_id=telegram_user_id,
        outcome=VisitForceOutcome.CREATED_EXTRA.value,
        incident_source=IncidentSource.NO_SALES.value,
        machine_display="Аппарат 101",
        location_display=None,
        occurred_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
    )


def test_visit_force_notify_handler_sends_ops_and_dm() -> None:
    """happy: ops + DM."""
    tg = _FakeTg()
    handler = VisitForceNotifyHandler(telegram=tg, ops_chat_id=-100)
    asyncio.run(handler.process(_event()))
    assert tg.sent[0] == (
        -100,
        "Технику Иван поставлена задача: Аппарат 101, причина no_sales",
    )
    assert tg.sent[1] == (42, "Новая задача: Аппарат 101")


def test_visit_force_notify_handler_skips_dm_without_telegram(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """edge: telegram_user_id None → один send (ops); caplog dm_skipped."""
    tg = _FakeTg()
    handler = VisitForceNotifyHandler(telegram=tg, ops_chat_id=-100)
    with caplog.at_level("INFO"):
        asyncio.run(handler.process(_event(telegram_user_id=None)))
    assert len(tg.sent) == 1
    assert tg.sent[0][0] == -100
    assert "visit_force_notify_dm_skipped_no_telegram" in caplog.text


def test_visit_force_notify_handler_boosted_reason_priority_boost() -> None:
    """happy: boosted_scheduled → reason priority_boost."""
    tg = _FakeTg()
    handler = VisitForceNotifyHandler(telegram=tg, ops_chat_id=-100)
    event = ServiceVisitForceNotifyRequested(
        event_id=EventId(visit_force_notify_event_id("sched:101", "g1")),
        visit_id="sched:101",
        machine_id=MachineId("101"),
        technician_id=TechnicianId("t1"),
        technician_display="Иван",
        telegram_user_id=None,
        outcome=VisitForceOutcome.BOOSTED_SCHEDULED.value,
        incident_source=IncidentSource.NO_SALES.value,
        machine_display="Аппарат 101",
        location_display=None,
        occurred_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
    )
    asyncio.run(handler.process(event))
    assert "причина priority_boost" in tg.sent[0][1]


def test_visit_force_notify_handler_telegram_failure_propagates() -> None:
    """error: Telegram fail → exception for outbox retry; visit already committed."""
    tg = _FakeTg(fail=True)
    handler = VisitForceNotifyHandler(telegram=tg, ops_chat_id=-100)
    with pytest.raises(RuntimeError, match="telegram down"):
        asyncio.run(handler.process(_event()))
