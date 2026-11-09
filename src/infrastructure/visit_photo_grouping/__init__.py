from __future__ import annotations

from typing import Self, cast

from beartype import beartype
from pydantic import model_validator

from src.application.visit_photo_grouping import (
    VISIT_PHOTO_GROUPING_HANDLER_ID,
    GroupAcceptedBatch,
    GroupClassifier,
)
from src.application.visit_photo_review import AssignBatchGroups, RecordMissingRequiredGroup
from src.application.visit_photo_review.ports import ReviewCatalogSource
from src.config._base import ServiceSettingsBase
from src.domain.machine_operations.events import PhotosSubmitted
from src.infrastructure.outbox.processor import OutboxHandler, OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.visit_photo_grouping.batch_reader import (
    PhotoBatchGroupingReader,
    PhotoBatchLookup,
)
from src.infrastructure.visit_photo_grouping.openclip_classifier import OpenClipGroupClassifier
from src.infrastructure.visit_photo_grouping.outbox_handler import VisitPhotoGroupingOutboxHandler
from src.infrastructure.visit_photo_grouping.participation import (
    AlwaysIncluded,
    MachineLookup,
    MasterMachineReviewParticipation,
)

__all__ = [
    "VISIT_PHOTO_GROUPING_HANDLER_ID",
    "AlwaysIncluded",
    "MasterMachineReviewParticipation",
    "OpenClipGroupClassifier",
    "PhotoBatchGroupingReader",
    "VisitPhotoGroupingOutboxHandler",
    "build_visit_photo_grouping_handler",
    "register_visit_photo_grouping",
    "subscribe_visit_photo_grouping",
]


class _GroupingHandlerGate(ServiceSettingsBase):
    enabled: bool
    classifier_present: bool
    commands_present: bool

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.enabled:
            return self
        if not self.classifier_present:
            raise ValueError(
                "GroupClassifier is required when VISIT_PHOTO_GROUPING_ENABLED=true",
            )
        if not self.commands_present:
            raise ValueError(
                "visit photo review command dependencies are required when "
                "VISIT_PHOTO_GROUPING_ENABLED=true",
            )
        return self


@beartype
def build_visit_photo_grouping_handler(
    *,
    enabled: bool,
    photo_batch_store: PhotoBatchLookup,
    machines: MachineLookup | None,
    classifier: object | None,
    catalog: object | None,
    assign: object | None,
    missing: object | None,
    not_ready_retry_minutes: int = 5,
    not_ready_max_attempts: int = 24,
) -> VisitPhotoGroupingOutboxHandler | None:
    if not enabled:
        return None
    _GroupingHandlerGate(
        enabled=True,
        classifier_present=classifier is not None,
        commands_present=catalog is not None and assign is not None and missing is not None,
    )
    participation: AlwaysIncluded | MasterMachineReviewParticipation
    if machines is None:
        participation = AlwaysIncluded()
    else:
        participation = MasterMachineReviewParticipation(machines)
    use_case = GroupAcceptedBatch(
        batches=PhotoBatchGroupingReader(photo_batch_store),
        participation=participation,
        classifier=cast(GroupClassifier, classifier),
        catalog=cast(ReviewCatalogSource, catalog),
        assign=cast(AssignBatchGroups, assign),
        missing=cast(RecordMissingRequiredGroup, missing),
    )
    return VisitPhotoGroupingOutboxHandler(
        use_case,
        not_ready_retry_minutes=not_ready_retry_minutes,
        not_ready_max_attempts=not_ready_max_attempts,
    )


@beartype
def subscribe_visit_photo_grouping(
    *,
    publisher: OutboxDomainEventPublisher,
    enabled: bool,
) -> None:
    """App enqueue-only: create outbox rows without registering a processor."""
    if not enabled:
        return
    publisher.subscribe(PhotosSubmitted, VISIT_PHOTO_GROUPING_HANDLER_ID)


@beartype
def register_visit_photo_grouping(
    *,
    publisher: OutboxDomainEventPublisher,
    processors: OutboxProcessorRegistry,
    enabled: bool,
    handler: VisitPhotoGroupingOutboxHandler | None,
) -> None:
    if not enabled:
        return
    if handler is None:
        raise RuntimeError(
            "visit_photo_grouping_handler is required when VISIT_PHOTO_GROUPING_ENABLED=true",
        )
    processors.register(
        VISIT_PHOTO_GROUPING_HANDLER_ID,
        cast(OutboxHandler, handler.process),
    )
    publisher.subscribe(PhotosSubmitted, VISIT_PHOTO_GROUPING_HANDLER_ID)
