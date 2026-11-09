from __future__ import annotations

from datetime import date

from src.domain.event_reminders.parse import (
    ParsedEventRow,
    parse_sheet_rows,
)
from src.domain.event_reminders.select import (
    event_key,
    select_events_for_tick,
)


def test_parse_strict_ru_date_drops_time() -> None:
    rows = [["Дата", "Локация", "Комментарий"], ["29.04.2021 15:30:00", "База", "x"]]
    out = parse_sheet_rows(rows)
    assert out.events == (
        ParsedEventRow(event_date=date(2021, 4, 29), location="База", comment="x"),
    )
    assert out.bad_rows == ()


def test_parse_rejects_iso_and_two_digit_year() -> None:
    rows = [
        ["h", "h", "h"],
        ["2021-04-29", "A", ""],
        ["29.04.21", "B", ""],
    ]
    out = parse_sheet_rows(rows)
    assert out.events == ()
    assert len(out.bad_rows) == 2
    assert out.bad_rows[0].row_number == 2  # 1-based sheet


def test_blank_row_is_skipped() -> None:
    rows = [["h", "h", "h"], ["", "", ""], ["  ", " ", "\t"]]
    out = parse_sheet_rows(rows)
    assert out.events == ()
    assert out.bad_rows == ()


def test_empty_location_is_bad() -> None:
    rows = [["h", "h", "h"], ["29.04.2021", "  ", "c"]]
    out = parse_sheet_rows(rows)
    assert out.events == ()
    assert len(out.bad_rows) == 1


def test_event_key_stable_and_changes_with_comment() -> None:
    d = date(2026, 7, 29)
    k1 = event_key(d, "Loc", "c")
    k2 = event_key(d, "Loc", "c")
    k3 = event_key(d, "Loc", "c2")
    assert k1 == k2
    assert k1 != k3
    assert len(k1) == 64  # sha256 hex


def test_filter_matches_lead_days() -> None:
    today = date(2026, 7, 28)
    events = (
        ParsedEventRow(date(2026, 7, 29), "A", ""),  # 1 day
        ParsedEventRow(date(2026, 7, 31), "B", ""),  # 3 days
        ParsedEventRow(date(2026, 7, 30), "C", ""),  # 2 days — skip
        ParsedEventRow(date(2026, 7, 27), "D", ""),  # past — skip
    )
    selected = select_events_for_tick(events, today=today, lead_days=(1, 3))
    assert [e.location for e in selected] == ["A", "B"]


def test_unique_keeps_first_duplicate() -> None:
    today = date(2026, 7, 28)
    events = (
        ParsedEventRow(date(2026, 7, 29), "A", "c"),
        ParsedEventRow(date(2026, 7, 29), "A", "c"),
    )
    selected = select_events_for_tick(events, today=today, lead_days=(1,))
    assert len(selected) == 1
