from __future__ import annotations

from datetime import datetime, timedelta

from beartype import beartype

DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS = 300


@beartype
def stale_processing_cutoff(
    *,
    now: datetime,
    processing_lease_seconds: int = DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS,
) -> datetime:
    return now - timedelta(seconds=processing_lease_seconds)
