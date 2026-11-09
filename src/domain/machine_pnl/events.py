from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from beartype import beartype

from src.domain.ids import EventId


@beartype
@dataclass(frozen=True, slots=True)
class MachinePeriodPnlRequested:
    event_id: EventId
    period_id: str
    source_session_id: str
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class MachineMonthPnlRequested:
    event_id: EventId
    machine_id: str
    period_start_dates: tuple[date, ...]
    source_period_id: str
    occurred_at: datetime
