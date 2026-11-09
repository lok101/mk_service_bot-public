from __future__ import annotations

from src.application.visit_photo_grouping.dispose_unrecognized_index import (
    DisposeAction,
    DisposeError,
    DisposeUnrecognizedIndex,
)
from src.application.visit_photo_grouping.group_accepted_batch import (
    DeliveryKind,
    GroupAcceptedBatch,
    GroupingDelivery,
    GroupingRetryReason,
)
from src.application.visit_photo_grouping.pack_path import resolve_visit_photo_pack_dir
from src.application.visit_photo_grouping.ports import (
    GroupClassifier,
    GroupingBatchReader,
    GroupingBatchView,
    GroupingGroup,
    GroupingPermanentFailure,
    GroupingStoredFile,
    GroupingSuccess,
    GroupingTemporaryFailure,
    MachineReviewParticipation,
)

VISIT_PHOTO_GROUPING_HANDLER_ID = "visit_photo_grouping"

__all__ = [
    "VISIT_PHOTO_GROUPING_HANDLER_ID",
    "DeliveryKind",
    "DisposeAction",
    "DisposeError",
    "DisposeUnrecognizedIndex",
    "GroupAcceptedBatch",
    "GroupClassifier",
    "GroupingBatchReader",
    "GroupingBatchView",
    "GroupingDelivery",
    "GroupingGroup",
    "GroupingPermanentFailure",
    "GroupingRetryReason",
    "GroupingStoredFile",
    "GroupingSuccess",
    "GroupingTemporaryFailure",
    "MachineReviewParticipation",
    "resolve_visit_photo_pack_dir",
]
