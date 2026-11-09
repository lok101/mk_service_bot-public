from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from beartype import beartype

from src.infrastructure.alerting.telegram_log_handler import send_telegram_message

_logger = logging.getLogger(__name__)


@beartype
@dataclass(slots=True)
class TelegramSnackSaleUnresolvedAlertNotifier:
    bot_token: str
    chat_id: int
    _send: Callable[[str], None] | None = None
    _last_fingerprint: int | None = field(default=None, init=False, repr=False)

    @beartype
    def notify_unresolved_sales(self, *, count: int) -> None:
        if count <= 0:
            return
        if self._last_fingerprint == count:
            _logger.info(
                "snack_sale_unresolved_alert_suppressed",
                extra={"fingerprint": count},
            )
            return

        text = f"Snack sales poll: {count} unresolved/mismatch sale(s) (threshold alert)."
        try:
            if self._send is not None:
                self._send(text)
            else:
                send_telegram_message(
                    bot_token=self.bot_token,
                    chat_id=self.chat_id,
                    text=text,
                )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "snack_sale_unresolved_alert_failed count=%s error=%s",
                count,
                exc,
            )
            return

        self._last_fingerprint = count
        _logger.info(
            "snack_sale_unresolved_alert_sent",
            extra={"fingerprint": count},
        )
