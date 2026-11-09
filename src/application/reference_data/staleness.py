from __future__ import annotations

from datetime import datetime

from beartype import beartype

from src.application.reference_data.models import ReferenceDataSnapshot


@beartype
def evaluate_staleness(
    snapshot: ReferenceDataSnapshot | None,
    *,
    now: datetime,
    threshold_seconds: int,
) -> bool:
    if snapshot is None:
        return False
    age_seconds = (now - snapshot.last_fetched_at).total_seconds()
    return age_seconds > threshold_seconds
