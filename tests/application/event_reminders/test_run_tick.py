from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.application.event_reminders import run_event_reminders_tick


@dataclass
class FakeSheet:
    rows: list[list[str]]

    def read_event_rows(self) -> list[list[str]]:
        return self.rows


@dataclass
class FakeReminder:
    sent: list[str] = field(default_factory=list)
    fail_on: int | None = None

    def send_plain_pre_content(self, text: str) -> None:
        if self.fail_on is not None and len(self.sent) == self.fail_on:
            raise RuntimeError("telegram down")
        self.sent.append(text)


@dataclass
class FakeAlert:
    sent: list[str] = field(default_factory=list)

    def send_text(self, text: str) -> None:
        self.sent.append(text)


def test_tick_sends_matching_events() -> None:
    sheet = FakeSheet(
        [
            ["d", "l", "c"],
            ["29.07.2026", "A", "hello"],
            ["30.07.2026", "B", "skip"],  # 2 days if today=28.07.2026
        ]
    )
    reminder = FakeReminder()
    alert = FakeAlert()
    run_event_reminders_tick(
        sheet_source=sheet,
        reminder_notifier=reminder,
        alert_notifier=alert,
        today=date(2026, 7, 28),
        lead_days=(1,),
    )
    assert len(reminder.sent) == 1
    assert "Локация: A" in reminder.sent[0]
    assert "hello" in reminder.sent[0]
    assert alert.sent == []


def test_tick_alerts_bad_rows_summary() -> None:
    sheet = FakeSheet([["d", "l", "c"], ["bad", "A", ""], ["29.07.2026", "B", ""]])
    reminder = FakeReminder()
    alert = FakeAlert()
    run_event_reminders_tick(
        sheet_source=sheet,
        reminder_notifier=reminder,
        alert_notifier=alert,
        today=date(2026, 7, 28),
        lead_days=(1,),
    )
    assert len(alert.sent) == 1
    assert "2" in alert.sent[0] or "bad" in alert.sent[0].lower()
    assert len(reminder.sent) == 1


def test_tick_mid_batch_failure_stops_remaining() -> None:
    today = date(2026, 7, 28)
    sheet = FakeSheet(
        [
            ["d", "l", "c"],
            ["29.07.2026", "A", "aaaaaaaaaa"],
            ["29.07.2026", "B", "bbbbbbbbbb"],
        ]
    )
    reminder = FakeReminder(fail_on=1)
    alert = FakeAlert()
    run_event_reminders_tick(
        sheet_source=sheet,
        reminder_notifier=reminder,
        alert_notifier=alert,
        today=today,
        lead_days=(1,),
        max_plain_len=80,
    )
    assert len(reminder.sent) == 1
    assert len(alert.sent) >= 1


def test_tick_alerts_oversized_event() -> None:
    sheet = FakeSheet(
        [
            ["d", "l", "c"],
            ["29.07.2026", "A", "x" * 5000],
            ["29.07.2026", "B", "ok"],
        ]
    )
    reminder = FakeReminder()
    alert = FakeAlert()
    run_event_reminders_tick(
        sheet_source=sheet,
        reminder_notifier=reminder,
        alert_notifier=alert,
        today=date(2026, 7, 28),
        lead_days=(1,),
        max_plain_len=100,
    )
    assert len(reminder.sent) == 1
    assert "Локация: B" in reminder.sent[0]
    assert any("oversized" in text for text in alert.sent)


def test_tick_sheet_failure_alerts_and_aborts() -> None:
    class BoomSheet:
        def read_event_rows(self) -> list[list[str]]:
            raise RuntimeError("sheets down")

    alert = FakeAlert()
    reminder = FakeReminder()
    run_event_reminders_tick(
        sheet_source=BoomSheet(),
        reminder_notifier=reminder,
        alert_notifier=alert,
        today=date(2026, 7, 28),
        lead_days=(1,),
    )
    assert reminder.sent == []
    assert len(alert.sent) == 1
