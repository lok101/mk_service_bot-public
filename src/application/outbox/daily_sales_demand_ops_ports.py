from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype


@runtime_checkable
class DailySalesDemandOpsTerminalAlerter(Protocol):
    """Ops TG on TELEGRAM_ALERT_CHAT_ID for terminal daily_sales_demand failures."""

    @beartype
    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        sales_day: str | None,
        event_id: str | None,
    ) -> None: ...
