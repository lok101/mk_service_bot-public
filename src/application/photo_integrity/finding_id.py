from __future__ import annotations

import uuid

from beartype import beartype

from src.domain.ids import BatchId, FindingId

_FINDING_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "mk-service-bot.photo-integrity-finding")


@beartype
def deterministic_photo_integrity_finding_id(
    *,
    batch_id: BatchId,
    photo_index: int,
    content_hash: str,
) -> FindingId:
    key = f"{batch_id.value}:{photo_index}:{content_hash}"
    return FindingId(uuid.uuid5(_FINDING_ID_NAMESPACE, key).hex)
