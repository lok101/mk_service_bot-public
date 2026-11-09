from __future__ import annotations

from datetime import date

from beartype import beartype

from src.application.event_reminders.ports import (
    AlertNotifier,
    EventSheetSource,
    ReminderNotifier,
)
from src.domain.event_reminders.format_message import (
    TELEGRAM_HTML_MESSAGE_MAX,
    TELEGRAM_PRE_PLAIN_MAX,
    chunk_plain_blocks_with_skips,
    format_bad_rows_summary,
    format_event_block,
    telegram_pre_content_len,
)
from src.domain.event_reminders.parse import parse_sheet_rows
from src.domain.event_reminders.select import select_events_for_tick

_BAD_ROWS_ALERT_MAX = TELEGRAM_HTML_MESSAGE_MAX


@beartype
def run_event_reminders_tick(
    *,
    sheet_source: EventSheetSource,
    reminder_notifier: ReminderNotifier,
    alert_notifier: AlertNotifier,
    today: date,
    lead_days: tuple[int, ...],
    max_plain_len: int = TELEGRAM_PRE_PLAIN_MAX,
) -> None:
    """One cron tick: sheet → parse/filter/format → Telegram (no persist)."""
    try:
        rows = sheet_source.read_event_rows()
    except Exception as exc:
        alert_notifier.send_text(f"event_reminders: sheets fail: {exc}")
        return

    outcome = parse_sheet_rows(rows)
    if outcome.bad_rows:
        alert_notifier.send_text(
            format_bad_rows_summary(outcome.bad_rows, max_len=_BAD_ROWS_ALERT_MAX)
        )

    selected = select_events_for_tick(
        outcome.events,
        today=today,
        lead_days=lead_days,
    )
    if not selected:
        return

    blocks = tuple(format_event_block(event) for event in selected)
    chunks, skipped = chunk_plain_blocks_with_skips(blocks, max_plain_len=max_plain_len)
    for skipped_block in skipped:
        alert_notifier.send_text(
            "event_reminders: oversized event skipped "
            f"({telegram_pre_content_len(skipped_block)} escaped chars)"
        )

    for chunk in chunks:
        try:
            reminder_notifier.send_plain_pre_content(chunk)
        except Exception as exc:
            alert_notifier.send_text(f"event_reminders: telegram fail: {exc}")
            return
