from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.ids import EventId


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketShopListPublishRequested:
    event_id: EventId
    machine_code: str
    publication_id: str
    lines: tuple[tuple[str, str, int, bool], ...]
    occurred_at: datetime
