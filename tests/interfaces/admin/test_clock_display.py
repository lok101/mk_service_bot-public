from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.interfaces.admin.clock_display import admin_moment_sort_key, format_admin_moment
from src.interfaces.admin.incident_history_view import (
    incident_history_choices,
    present_incident_history_row,
)

_MOSCOW = ZoneInfo("Europe/Moscow")
_OPENED = datetime(2026, 9, 28, 10, 8, 26, 618000, tzinfo=UTC)
_CLEARED = _OPENED + timedelta(hours=2, minutes=30)


def test_format_admin_moment_uses_display_timezone_to_the_minute() -> None:
    assert format_admin_moment(_OPENED, _MOSCOW) == "28.09.26 13:08"


def test_format_admin_moment_reads_naive_datetime_as_utc() -> None:
    naive = datetime(2026, 9, 28, 10, 8, 26, 618000)
    assert format_admin_moment(naive, _MOSCOW) == "28.09.26 13:08"
    assert admin_moment_sort_key(naive) == admin_moment_sort_key(_OPENED)


def test_format_admin_moment_blank_is_em_dash() -> None:
    assert format_admin_moment(None, _MOSCOW) == "—"
    assert admin_moment_sort_key(None) == ""


def test_present_incident_history_row_floors_open_duration_hours() -> None:
    row = present_incident_history_row(
        machine_id="137",
        name="Точка А",
        opened_at=_OPENED,
        cleared_at=_CLEARED,
        technician="Иван",
        reason=None,
        clear_kind="cleared",
        timezone=_MOSCOW,
    )
    assert row.machine_id == "137"
    assert row.name == "Точка А"
    assert row.opened_at == "28.09.26 13:08"
    assert row.cleared_at == "28.09.26 15:38"
    assert row.duration_hours == "2"
    assert row.duration_sort == "2"


def test_present_incident_history_row_blank_duration_when_not_cleared() -> None:
    row = present_incident_history_row(
        machine_id="137",
        name="—",
        opened_at=_OPENED,
        cleared_at=None,
        technician="",
        reason=None,
        clear_kind="",
        timezone=_MOSCOW,
    )
    assert row.duration_hours == "—"
    assert row.duration_sort == ""
    assert row.cleared_at == "—"


def test_present_incident_history_row_blank_duration_when_cleared_before_opened() -> None:
    row = present_incident_history_row(
        machine_id="137",
        name="—",
        opened_at=_CLEARED,
        cleared_at=_OPENED,
        technician="",
        reason=None,
        clear_kind="cleared",
        timezone=_MOSCOW,
    )
    assert row.duration_hours == "—"
    assert row.duration_sort == ""


def test_present_incident_history_row_keeps_blank_clear_as_em_dash() -> None:
    row = present_incident_history_row(
        machine_id="137",
        name="—",
        opened_at=_OPENED,
        cleared_at=None,
        technician="",
        reason=None,
        clear_kind="",
        timezone=_MOSCOW,
    )
    assert row.name == "—"
    assert row.opened_at == "28.09.26 13:08"
    assert row.opened_sort == admin_moment_sort_key(_OPENED)
    assert row.cleared_at == "—"
    assert row.cleared_sort == ""
    assert row.duration_hours == "—"
    assert row.technician == "—"
    assert row.reason == "—"
    assert row.clear_kind == "—"


def test_incident_history_choices_are_unique_and_casefold_sorted() -> None:
    assert incident_history_choices(["cleared", "—", "cleared", "Muted"]) == (
        "cleared",
        "Muted",
        "—",
    )
