from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.form_submissions import FormSubmissionValidationError
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import TechnicianWarehouseInventoryTokenPayload
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted


@beartype
@dataclass(frozen=True, slots=True)
class UnconfiguredAcceptTechnicianWarehouseInventory:
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> TechnicianWarehouseInventoryCounted:
        _ = (form_id, submitted_at, form_token, token_payload, answers)
        raise FormSubmissionValidationError("Склад техника временно недоступен.")


@beartype
@dataclass(frozen=True, slots=True)
class NoOpDirectWarehouseChatNotifier:
    async def notify(
        self,
        *,
        technician_id: TechnicianId,
        reason: str,
    ) -> None:
        _ = (technician_id, reason)
        return None


@beartype
@dataclass(frozen=True, slots=True)
class WebhookPlaceholderBot:
    async def send_message(self, **kwargs: object) -> None:
        _ = kwargs
        return None
