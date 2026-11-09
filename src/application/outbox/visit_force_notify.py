from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.service_visits import VisitForceOutcome
from src.application.service_visits.force_notify_format import (
    format_dm_force_notify,
    format_ops_force_notify,
)
from src.domain.events import DomainEvent
from src.domain.service_visits import ServiceVisitForceNotifyRequested

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class VisitForceNotifyTelegram(Protocol):
    async def send_message(self, *, chat_id: int, text: str) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class VisitForceNotifyHandler:
    telegram: VisitForceNotifyTelegram
    ops_chat_id: int

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, ServiceVisitForceNotifyRequested):
            raise NonRetryableOutboxError(
                f"Unsupported event: {type(event).__name__}",
            )
        machine_display = event.machine_display or event.machine_id.value
        reason = (
            "priority_boost"
            if event.outcome == VisitForceOutcome.BOOSTED_SCHEDULED
            else (event.incident_source or event.outcome)
        )
        ops_text = format_ops_force_notify(
            technician_display=event.technician_display,
            machine_display=machine_display,
            reason=reason,
        )
        await self.telegram.send_message(chat_id=self.ops_chat_id, text=ops_text)
        _LOGGER.info(
            "visit_force_notify_ops_sent",
            extra={"chat_id": self.ops_chat_id, "visit_id": event.visit_id},
        )
        if event.telegram_user_id is None:
            _LOGGER.info(
                "visit_force_notify_dm_skipped_no_telegram",
                extra={
                    "technician_id": event.technician_id.value,
                    "visit_id": event.visit_id,
                },
            )
            return
        dm_text = format_dm_force_notify(machine_display=machine_display)
        await self.telegram.send_message(
            chat_id=event.telegram_user_id,
            text=dm_text,
        )
        _LOGGER.info(
            "visit_force_notify_dm_sent",
            extra={
                "telegram_user_id": event.telegram_user_id,
                "visit_id": event.visit_id,
            },
        )
