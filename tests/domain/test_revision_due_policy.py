from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.domain.calendar import calendar_anchor, end_of_service_calendar_day
from src.domain.ids import MachineId, RevisionId
from src.domain.revision_due_policy import (
    compute_responsibility_expires_at,
    compute_revision_due_status,
)

_MSK = ZoneInfo("Europe/Moscow")
_COMPLETED = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
_EXPIRES = datetime(2026, 5, 25, 0, 0, tzinfo=_MSK)


def test_calendar_anchor_is_local_midnight() -> None:
    value = datetime(2026, 5, 15, 21, 30, tzinfo=UTC)  # 00:30 MSK 16-го
    anchor = calendar_anchor(value, _MSK)
    assert anchor == datetime(2026, 5, 16, 0, 0, tzinfo=_MSK)


def test_end_of_service_calendar_day() -> None:
    anchor = datetime(2026, 5, 25, 0, 0, tzinfo=_MSK)
    end = end_of_service_calendar_day(anchor.date(), _MSK)
    assert end == datetime(2026, 5, 25, 23, 59, 59, 999999, tzinfo=_MSK)


def test_compute_responsibility_expires_at_is_stable() -> None:
    kwargs = dict(
        machine_id=MachineId("vm-01"),
        revision_id=RevisionId("rev-1"),
        completed_at=_COMPLETED,
        min_days=10,
        max_days=12,
        service_calendar_timezone=_MSK,
    )
    first = compute_responsibility_expires_at(**kwargs)
    second = compute_responsibility_expires_at(**kwargs)
    assert first == second


def test_compute_responsibility_expires_at_spreads_deadlines() -> None:
    kwargs = dict(
        completed_at=_COMPLETED,
        min_days=10,
        max_days=12,
        service_calendar_timezone=_MSK,
    )
    expires_a = compute_responsibility_expires_at(
        machine_id=MachineId("vm-01"),
        revision_id=RevisionId("rev-a"),
        **kwargs,
    )
    expires_b = compute_responsibility_expires_at(
        machine_id=MachineId("vm-02"),
        revision_id=RevisionId("rev-b"),
        **kwargs,
    )
    anchor = datetime(2026, 5, 15, 0, 0, tzinfo=_MSK)
    min_deadline = datetime.combine(
        anchor.date() + timedelta(days=10),
        time.min,
        tzinfo=_MSK,
    )
    max_deadline = datetime.combine(
        anchor.date() + timedelta(days=12),
        time.min,
        tzinfo=_MSK,
    )
    assert min_deadline <= expires_a <= max_deadline
    assert min_deadline <= expires_b <= max_deadline
    assert expires_a != expires_b


def test_compute_responsibility_expires_at_uses_start_of_deadline_day() -> None:
    expires = compute_responsibility_expires_at(
        machine_id=MachineId("vm-01"),
        revision_id=RevisionId("rev-1"),
        completed_at=_COMPLETED,
        min_days=10,
        max_days=10,
        service_calendar_timezone=_MSK,
    )
    assert expires == datetime(2026, 5, 25, 0, 0, tzinfo=_MSK)


def test_revision_due_status_binary_not_due_or_overdue() -> None:
    before = compute_revision_due_status(
        expires_at=_EXPIRES,
        checked_at=_EXPIRES - timedelta(seconds=1),
    )
    at_boundary = compute_revision_due_status(
        expires_at=_EXPIRES,
        checked_at=_EXPIRES,
    )
    assert before == "not_due"
    assert at_boundary == "overdue"
    assert {before, at_boundary} == {"not_due", "overdue"}


def test_revision_due_status_not_due() -> None:
    checked_at = _EXPIRES - timedelta(days=1)
    assert (
        compute_revision_due_status(
            expires_at=_EXPIRES,
            checked_at=checked_at,
        )
        == "not_due"
    )


def test_revision_due_status_overdue() -> None:
    assert (
        compute_revision_due_status(
            expires_at=_EXPIRES,
            checked_at=_EXPIRES,
        )
        == "overdue"
    )
