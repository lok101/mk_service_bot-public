from __future__ import annotations

__all__ = [
    "StatusBoardMessageGoneError",
    "StatusBoardNotModifiedError",
    "StatusBoardTelegramError",
]


class StatusBoardTelegramError(Exception):
    """Telegram board HTTP failed (keep pointer)."""


class StatusBoardMessageGoneError(StatusBoardTelegramError):
    """edit: message to edit not found / deleted."""


class StatusBoardNotModifiedError(StatusBoardTelegramError):
    """edit: message is not modified."""
