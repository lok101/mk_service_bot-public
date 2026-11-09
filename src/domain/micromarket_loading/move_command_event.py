from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.ids import EventId


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketLoadingMoveCommandRequested:
    event_id: EventId
    command_id: str
    occurred_at: datetime
