from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.calendar import calendar_anchor
from src.domain.ids import MachineId, RevisionId
from src.domain.results import RevisionDueStatus


@beartype
def compute_responsibility_expires_at(
    *,
    machine_id: MachineId,
    revision_id: RevisionId,
    completed_at: datetime,
    min_days: int,
    max_days: int,
    service_calendar_timezone: ZoneInfo,
) -> datetime:
    spread_days = max_days - min_days + 1
    digest = hashlib.sha256(f"{machine_id}:{revision_id}".encode()).digest()
    offset_days = int.from_bytes(digest[:8], "big") % spread_days
    anchor = calendar_anchor(completed_at, service_calendar_timezone)
    deadline_day = anchor.date() + timedelta(days=min_days + offset_days)
    return datetime.combine(deadline_day, time.min, tzinfo=service_calendar_timezone)


@beartype
def compute_revision_due_status(
    *,
    expires_at: datetime,
    checked_at: datetime,
) -> RevisionDueStatus:
    if checked_at >= expires_at:
        return "overdue"
    return "not_due"
