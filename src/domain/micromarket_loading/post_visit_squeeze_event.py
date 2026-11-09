from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.ids import EventId


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPostVisitSqueezeRequested:
    """Outbox command: drain Load → publish → post invent for pending invent."""

    event_id: EventId
    machine_code: str
    inventory_id: str
    occurred_at: datetime
