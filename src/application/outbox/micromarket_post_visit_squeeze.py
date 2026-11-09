from __future__ import annotations

import logging
from dataclasses import dataclass

from beartype import beartype

from src.application.micromarket_loading.post_visit_squeeze import PostVisitSqueeze
from src.domain.events import DomainEvent
from src.domain.micromarket_loading.post_visit_squeeze_event import (
    MicromarketPostVisitSqueezeRequested,
)

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPostVisitSqueezeOutboxHandler:
    """effects-worker drain: run PostVisitSqueeze stages for enqueued invent."""

    squeeze: PostVisitSqueeze

    @beartype
    def process(self, event: DomainEvent) -> None:
        if not isinstance(event, MicromarketPostVisitSqueezeRequested):
            raise TypeError(type(event).__name__)
        _logger.info(
            "micromarket_post_visit_squeeze_drain",
            extra={
                "machine_code": event.machine_code,
                "inventory_id": event.inventory_id,
            },
        )
        self.squeeze.run(
            machine_code=event.machine_code,
            inventory_id=event.inventory_id,
        )
