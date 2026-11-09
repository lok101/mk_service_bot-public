from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from beartype import beartype

from src.domain.ids import EventId, MachineId

NoSalesIncidentControlAction = Literal["mute", "mute_cancel", "engineer_wait"]


@beartype
@dataclass(frozen=True, slots=True)
class NoSalesIncidentControlRequested:
    event_id: EventId
    occurred_at: datetime
    machine_id: MachineId
    opened_event_id: str
    action: NoSalesIncidentControlAction
    mute_event_id: str | None
