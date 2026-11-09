"""Ports for event reminders BC."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EventSheetSource(Protocol):
    def read_event_rows(self) -> list[list[str]]:
        """Return sheet rows A–C as formatted strings (including header)."""


@runtime_checkable
class ReminderNotifier(Protocol):
    def send_plain_pre_content(self, text: str) -> None:
        """Send plain text; adapter wraps HTML <pre> + escape."""


@runtime_checkable
class AlertNotifier(Protocol):
    def send_text(self, text: str) -> None:
        """Send ops alert text (plain or HTML — adapter decides)."""
