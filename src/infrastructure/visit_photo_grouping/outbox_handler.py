from __future__ import annotations

import logging
from datetime import timedelta
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import DeferredRetryOutboxError, NonRetryableOutboxError
from src.application.visit_photo_grouping import DeliveryKind, GroupingDelivery
from src.domain.machine_operations.events import PhotosSubmitted

logger = logging.getLogger(__name__)


@runtime_checkable
class GroupingExecutor(Protocol):
    @beartype
    def execute(self, batch_id: str) -> GroupingDelivery: ...


@beartype
class VisitPhotoGroupingOutboxHandler:
    def __init__(
        self,
        use_case: GroupingExecutor,
        *,
        not_ready_retry_minutes: int = 5,
        not_ready_max_attempts: int = 24,
    ) -> None:
        self._use_case = use_case
        self._not_ready_retry_minutes = not_ready_retry_minutes
        self._not_ready_max_attempts = not_ready_max_attempts

    @beartype
    async def process(self, event: PhotosSubmitted) -> None:
        delivery = self._use_case.execute(event.batch_id.value)
        if delivery.kind is DeliveryKind.SUCCESS:
            return
        if delivery.kind is DeliveryKind.RETRY:
            reason = delivery.reason.value if delivery.reason is not None else "retry"
            raise DeferredRetryOutboxError(
                f"{reason} batch_id={delivery.batch_id} machine_id={delivery.machine_id}",
                delay=timedelta(minutes=self._not_ready_retry_minutes),
                max_attempts=self._not_ready_max_attempts,
            )
        logger.warning(
            "visit photo grouping permanent refusal batch_id=%s machine_id=%s",
            delivery.batch_id,
            delivery.machine_id,
        )
        raise NonRetryableOutboxError("visit photo grouping refused")
