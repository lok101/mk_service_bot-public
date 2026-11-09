from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from beartype import beartype

_STRICT_RU_DATE = re.compile(r"^(?P<date>\d{2}\.\d{2}\.\d{4})(?:\s+\S.*)?$")


@dataclass(frozen=True, slots=True)
class ParsedEventRow:
    event_date: date
    location: str
    comment: str


@dataclass(frozen=True, slots=True)
class BadRow:
    row_number: int
    preview: str


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    events: tuple[ParsedEventRow, ...]
    bad_rows: tuple[BadRow, ...]


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return str(row[index]).strip()


def _row_preview(date_raw: str, location: str, comment: str) -> str:
    return f"{date_raw}|{location}|{comment}"


def _parse_event_date(raw: str) -> date | None:
    match = _STRICT_RU_DATE.fullmatch(raw)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group("date"), "%d.%m.%Y").date()
    except ValueError:
        return None


@beartype
def parse_sheet_rows(rows: list[list[str]]) -> ParseOutcome:
    """Parse sheet rows A–C; skip header (index 0); blank rows silent-skip."""
    events: list[ParsedEventRow] = []
    bad_rows: list[BadRow] = []
    if not rows:
        return ParseOutcome(events=(), bad_rows=())

    for index, row in enumerate(rows[1:], start=2):  # 1-based sheet row
        date_raw = _cell(row, 0)
        location = _cell(row, 1)
        comment = _cell(row, 2)
        if not date_raw and not location and not comment:
            continue
        event_date = _parse_event_date(date_raw)
        if event_date is None or not location:
            bad_rows.append(
                BadRow(
                    row_number=index,
                    preview=_row_preview(date_raw, location, comment),
                )
            )
            continue
        events.append(
            ParsedEventRow(
                event_date=event_date,
                location=location,
                comment=comment,
            )
        )
    return ParseOutcome(events=tuple(events), bad_rows=tuple(bad_rows))
